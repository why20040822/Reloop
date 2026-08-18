/** Retry policy for transient local-service failures. Classic script by design. */
(function (root) {
  'use strict';
  if (root.__TTC_RETRY_POLICY) return;

  const TRANSIENT_ERROR = /failed to fetch|networkerror|network request failed|load failed|本地服务不可用|扩展后台无响应|message port closed/i;

  function delayMs(attempt) {
    const safeAttempt = Math.max(1, Math.min(20, Number(attempt) || 1));
    return Math.min(60000, 5000 * (2 ** (safeAttempt - 1)));
  }

  function shouldKeepRetrying(error, attempt) {
    const message = error && error.message ? error.message : String(error || '');
    return Number(attempt) < 4 || TRANSIENT_ERROR.test(message);
  }

  root.__TTC_RETRY_POLICY = Object.freeze({delayMs, shouldKeepRetrying});
})(globalThis);
