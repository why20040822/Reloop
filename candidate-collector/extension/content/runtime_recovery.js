/**
 * Recover BOSS tabs that still contain content scripts from an older extension
 * context after the unpacked extension is reloaded.
 *
 * Chrome does not reinject new content scripts into an already-open page when
 * an extension is reloaded. The old scripts keep their timers, but every
 * chrome.runtime/Port call then throws "Extension context invalidated". A
 * single guarded page refresh is the only reliable way to attach the new
 * extension context.
 */
(function (root) {
  'use strict';

  const STORAGE_KEY = 'ot_runtime_recovery_v1';
  const NOTICE_ID = 'ot-runtime-recovery-notice';
  const INVALIDATED_EVENT = 'ot:extension-context-invalidated';
  const HEALTHY_RESET_MS = 30_000;
  const CHECK_INTERVAL_MS = 3_000;
  const RELOAD_DELAY_MS = 450;
  const COPILOT_USER_STATUS_PATH =
    '/api/user_service/v1/internal/user/batch/unionids';
  const COPILOT_SERVICE_HOSTS = new Set([
    'app.ttcadvisory.com',
    'int.ttcadvisory.com'
  ]);
  const INVALID_CONTEXT_ERROR =
    /Extension context invalidated|Attempting to use a disconnected port object/i;

  function errorText(value) {
    if (value instanceof Error) return value.message || String(value);
    if (value && typeof value === 'object' && typeof value.message === 'string') {
      return value.message;
    }
    return String(value || '');
  }

  function isRecoverableError(value) {
    return INVALID_CONTEXT_ERROR.test(errorText(value));
  }

  function isBossPage(locationValue) {
    try {
      const hostname = String(locationValue && locationValue.hostname || '');
      return /(?:^|\.)zhipin\.com$/i.test(hostname);
    } catch (_error) {
      return false;
    }
  }

  function runtimeAlive(chromeValue) {
    try {
      if (!chromeValue || !chromeValue.runtime || !chromeValue.runtime.id) return false;
      const manifest = chromeValue.runtime.getManifest();
      return Boolean(manifest && manifest.version);
    } catch (_error) {
      return false;
    }
  }

  function isCopilotUserStatusRequest(data) {
    try {
      const url = new URL(String(data && data.url || ''));
      return Boolean(
        data &&
        data.type === 'fetchData' &&
        typeof data.requestId === 'string' &&
        data.requestId &&
        String(data.method || 'POST').toUpperCase() === 'POST' &&
        url.protocol === 'https:' &&
        COPILOT_SERVICE_HOSTS.has(url.hostname) &&
        url.pathname === COPILOT_USER_STATUS_PATH &&
        !url.search &&
        !url.hash
      );
    } catch (_error) {
      return false;
    }
  }

  function readRecoveryState(storage) {
    try {
      const parsed = JSON.parse(storage.getItem(STORAGE_KEY) || 'null');
      if (parsed && Number.isFinite(Number(parsed.attempts))) {
        return {
          attempts: Math.max(0, Number(parsed.attempts) || 0)
        };
      }
    } catch (_error) {
      // The caller will require a successful latch write before auto-refresh.
    }
    return {attempts: 0};
  }

  function writeRecoveryState(storage, state) {
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(state));
      return storage.getItem(STORAGE_KEY) != null;
    } catch (_error) {
      return false;
    }
  }

  function clearRecoveryState(storage) {
    try {
      storage.removeItem(STORAGE_KEY);
    } catch (_error) {
      // Nothing else is required.
    }
  }

  function showNotice(documentValue, message, danger) {
    if (!documentValue || !documentValue.documentElement) return;
    const attach = () => {
      const parent = documentValue.body || documentValue.documentElement;
      let notice = documentValue.getElementById(NOTICE_ID);
      if (!notice) {
        notice = documentValue.createElement('div');
        notice.id = NOTICE_ID;
        notice.setAttribute('role', 'status');
        notice.style.cssText = [
          'position:fixed',
          'right:24px',
          'bottom:24px',
          'z-index:2147483646',
          'max-width:380px',
          'padding:12px 16px',
          'border:1px solid #e7e7ea',
          'border-left:4px solid #2563eb',
          'border-radius:12px',
          'background:#fff',
          'color:#18181b',
          'box-shadow:0 8px 24px rgba(0,0,0,.12)',
          'font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif'
        ].join(';');
        parent.appendChild(notice);
      }
      notice.style.borderLeftColor = danger ? '#dc2626' : '#2563eb';
      notice.textContent = message;
    };
    if (documentValue.body) attach();
    else documentValue.addEventListener('DOMContentLoaded', attach, {once: true});
  }

  function createRuntimeRecovery(environment = {}) {
    const windowValue = environment.window || root.window;
    const documentValue = environment.document || root.document;
    const locationValue = environment.location || root.location;
    const chromeValue = environment.chrome || root.chrome;
    const consoleValue = environment.console || root.console;
    const storage = environment.sessionStorage || root.sessionStorage;
    const setTimeoutValue = environment.setTimeout || root.setTimeout.bind(root);
    const setIntervalValue = environment.setInterval || root.setInterval.bind(root);
    const clearIntervalValue = environment.clearInterval || root.clearInterval.bind(root);
    let recovering = false;
    let inMemoryAttempts = 0;
    let intervalId = null;
    let originalConsoleError = null;
    let patchedConsoleError = null;
    let userStatusBridgeInstalled = false;

    function onCopilotFetch(event) {
      const data = event && event.data;
      if (!isCopilotUserStatusRequest(data)) return;
      if (event.source && event.source !== windowValue) return;
      if (
        !chromeValue ||
        !chromeValue.runtime ||
        typeof chromeValue.runtime.sendMessage !== 'function'
      ) {
        return;
      }

      // This capture listener is installed before the upstream content script.
      // Stop only the fixed TTC user-status request from reaching its shared
      // `fetchData` channel, then use a uniquely named, allowlisted route.
      if (typeof event.stopImmediatePropagation === 'function') {
        event.stopImmediatePropagation();
      }
      if (typeof event.stopPropagation === 'function') event.stopPropagation();

      const requestId = data.requestId;
      const respond = response => {
        let result = response;
        try {
          const runtimeError = chromeValue.runtime.lastError;
          if (runtimeError) {
            const message = errorText(runtimeError) || '扩展后台连接失败';
            result = {success: false, error: message, data: message};
          }
        } catch (error) {
          const message = errorText(error) || '扩展后台连接失败';
          result = {success: false, error: message, data: message};
        }
        if (!result || typeof result !== 'object') {
          result = {
            success: false,
            error: '扩展后台未返回用户状态',
            data: '扩展后台未返回用户状态'
          };
        } else if (result.success !== true && !result.data) {
          result = Object.assign({}, result, {
            data: errorText(result.error) || '用户状态请求失败'
          });
        }
        windowValue.postMessage({
          type: 'fetchDataResponse',
          requestId,
          response: result
        }, '*');
      };

      try {
        chromeValue.runtime.sendMessage({
          type: 'otUserStatusFetch',
          requestId,
          url: data.url,
          method: 'POST',
          body: data.body
        }, respond);
      } catch (error) {
        const message = errorText(error) || '扩展后台连接失败';
        respond({success: false, error: message, data: message});
      }
    }

    function signalInvalidation(reason) {
      if (root.__OT_RUNTIME_RECOVERY__) {
        root.__OT_RUNTIME_RECOVERY__.invalidated = true;
      }
      try {
        const EventType = environment.CustomEvent || root.CustomEvent;
        if (windowValue && typeof windowValue.dispatchEvent === 'function' && EventType) {
          windowValue.dispatchEvent(new EventType(INVALIDATED_EVENT, {
            detail: {reason: errorText(reason)}
          }));
        }
      } catch (_error) {
        // The global invalidated flag remains available to later scripts.
      }
    }

    function recover(reason) {
      if (!isRecoverableError(reason) || !isBossPage(locationValue)) return false;
      signalInvalidation(reason);
      if (recovering) return false;
      const state = storage
        ? readRecoveryState(storage)
        : {attempts: inMemoryAttempts};
      inMemoryAttempts = state.attempts;

      if (state.attempts >= 1) {
        showNotice(
          documentValue,
          'ot小插件连接仍未恢复，请手动刷新当前 BOSS 页面。',
          true
        );
        return false;
      }

      recovering = true;
      state.attempts += 1;
      inMemoryAttempts = state.attempts;
      if (!storage || !writeRecoveryState(storage, state)) {
        recovering = false;
        showNotice(
          documentValue,
          'ot小插件连接已失效，请手动刷新当前 BOSS 页面。',
          true
        );
        return false;
      }
      showNotice(
        documentValue,
        'ot小插件刚刚完成更新，正在刷新当前 BOSS 页面以恢复连接…',
        false
      );
      setTimeoutValue(() => {
        try {
          locationValue.reload();
        } catch (_error) {
          recovering = false;
        }
      }, RELOAD_DELAY_MS);
      return true;
    }

    function onError(event) {
      const value = event && (event.error || event.message);
      if (!isRecoverableError(value)) return;
      if (event && typeof event.preventDefault === 'function') event.preventDefault();
      recover(value);
    }

    function onUnhandledRejection(event) {
      if (!isRecoverableError(event && event.reason)) return;
      if (event && typeof event.preventDefault === 'function') event.preventDefault();
      recover(event.reason);
    }

    function checkRuntime() {
      if (!runtimeAlive(chromeValue)) recover('Extension context invalidated');
    }

    function installConsoleRecovery() {
      if (!consoleValue || typeof consoleValue.error !== 'function') return;
      originalConsoleError = consoleValue.error;
      patchedConsoleError = function (...args) {
        const runtimeError = args.find(isRecoverableError);
        if (runtimeError) recover(runtimeError);
        return originalConsoleError.apply(this, args);
      };
      try {
        consoleValue.error = patchedConsoleError;
      } catch (_error) {
        originalConsoleError = null;
        patchedConsoleError = null;
      }
    }

    function install() {
      if (!windowValue || !isBossPage(locationValue)) return false;
      try {
        const manifest = chromeValue && chromeValue.runtime &&
          typeof chromeValue.runtime.getManifest === 'function'
          ? chromeValue.runtime.getManifest()
          : null;
        consoleValue.info(
          '[ot小插件] runtime v' + (manifest && manifest.version || '?') +
          ' 已注入 ' + String(locationValue.pathname || '')
        );
      } catch (_error) {
        // 版本水印仅用于现场诊断，注入失败不影响恢复逻辑。
      }
      windowValue.addEventListener('message', onCopilotFetch, true);
      userStatusBridgeInstalled = true;
      windowValue.addEventListener('error', onError, true);
      windowValue.addEventListener('unhandledrejection', onUnhandledRejection, true);
      installConsoleRecovery();
      intervalId = setIntervalValue(checkRuntime, CHECK_INTERVAL_MS);
      setTimeoutValue(() => {
        if (runtimeAlive(chromeValue) && storage) {
          clearRecoveryState(storage);
          if (root.__OT_RUNTIME_RECOVERY__) {
            root.__OT_RUNTIME_RECOVERY__.invalidated = false;
          }
        }
      }, HEALTHY_RESET_MS);
      return true;
    }

    function dispose() {
      if (!windowValue) return;
      windowValue.removeEventListener('error', onError, true);
      windowValue.removeEventListener('unhandledrejection', onUnhandledRejection, true);
      if (userStatusBridgeInstalled) {
        windowValue.removeEventListener('message', onCopilotFetch, true);
        userStatusBridgeInstalled = false;
      }
      if (
        consoleValue &&
        patchedConsoleError &&
        consoleValue.error === patchedConsoleError &&
        originalConsoleError
      ) {
        try {
          consoleValue.error = originalConsoleError;
        } catch (_error) {
          // The console implementation may be read-only.
        }
      }
      if (intervalId != null) clearIntervalValue(intervalId);
      intervalId = null;
    }

    return {
      checkRuntime,
      dispose,
      install,
      isRecovering: () => recovering,
      recover
    };
  }

  const api = {
    createRuntimeRecovery,
    invalidated: false,
    invalidatedEvent: INVALIDATED_EVENT,
    isCopilotUserStatusRequest,
    isBossPage,
    isRecoverableError,
    runtimeAlive
  };
  root.__OT_RUNTIME_RECOVERY__ = api;

  if (root.window && root.document && root.location) {
    api.instance = createRuntimeRecovery();
    api.instance.install();
  }
})(globalThis);
