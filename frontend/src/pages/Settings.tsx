import { useEffect, useState } from "react";
import { ChevronRight, CircleHelp, Database, LogIn } from "lucide-react";
import { DirectGlassSegment } from "../components/DirectGlassSegment";
import { AUTH_CHANGE_EVENT, api, config, type CurrentUser, type SyncStatus } from "../lib/api";
import { Notice, PageHeading, errorMessage } from "../components/ui";

export function SettingsPage({ loginError, authRevision, onLogin, onConnect }: { loginError: string; authRevision: number; onLogin: () => void; onConnect: () => void }) {
  const [cfg, setCfg] = useState(config.read());
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [preferenceMessage, setPreferenceMessage] = useState("");
  const [advancedMessage, setAdvancedMessage] = useState("");
  const [syncError, setSyncError] = useState("");
  const refreshUser = async () => { if (!config.auth()) { setUser(null); return; } try { setUser(await api.me()); } catch { config.clearAuth(); setUser(null); } };
  useEffect(() => { void refreshUser(); }, [authRevision]);
  const startSync = async () => {
    try {
      setSyncError("");
      const result = await api.syncTtc();
      const poll = async () => { const next = await api.syncStatus(result.sync_id); setSync(next); if (next.status === "running") setTimeout(() => void poll(), 1500); };
      await poll();
    } catch (error) { setSyncError(errorMessage(error)); }
  };
  const savePreferences = () => {
    setCfg(config.write({ locale: cfg.locale }));
    setPreferenceMessage("偏好已保存。");
  };
  const saveAdvancedSettings = () => {
    setCfg(config.write({ mode: cfg.mode, apiBase: cfg.apiBase }));
    setAdvancedMessage("高级设置已保存。");
  };
  return <div className="settings-page">
    <PageHeading
      title="设置"
      description="管理账号、人才库与使用偏好。"
      action={<button className="settings-help-button" type="button" aria-label="查看使用帮助" aria-expanded={helpOpen} title="使用帮助" onClick={() => setHelpOpen((open) => !open)}><CircleHelp size={19} /></button>}
    />
    {helpOpen && <section className="settings-help" aria-label="使用帮助"><strong>使用帮助</strong><p>访客模式读取共享人才库；登录后会自动连接并同步你的私有人才库。</p><p>真实 API、样本数据与后端地址位于高级设置中，普通使用无需调整。</p></section>}
    <section className="settings-panel settings-account-panel"><h2>账户与人才库</h2>{loginError && <Notice tone="error">{loginError}</Notice>}{user ? <><p>已登录为 <strong>{user.display_name}</strong> · 人才池 {user.pool_count} 人</p><p>{user.ttc_connected ? `已连接：${user.ttc_bound_name || "你的 TTC 人才库"}` : "尚未连接你的 TTC 人才库"}</p><div className="button-row">{!user.ttc_connected && <button className="secondary-button" type="button" onClick={onConnect}>连接人才库</button>}<button className="primary-button" type="button" onClick={() => void startSync()}>同步人才库</button><button className="text-button" type="button" onClick={() => { config.clearAuth(); setUser(null); }}>退出登录</button></div></> : <><p>登录飞书后，系统会自动连接并同步你的私有人才库。</p><button className="primary-button" type="button" onClick={onLogin}><LogIn size={16} />登录飞书</button></>}{syncError && <Notice tone="error">{syncError}</Notice>}{sync && <Notice tone={sync.status === "failed" ? "error" : "info"}>同步状态：{sync.status}{sync.total ? ` · ${sync.current || sync.processed || 0}/${sync.total}` : ""}{sync.error ? ` · ${sync.error}` : ""}</Notice>}</section>
    <section className="settings-panel"><h2>使用偏好</h2><label>语言<select value={cfg.locale} onChange={(event) => { setCfg({ ...cfg, locale: event.target.value as "zh-CN" | "en-US" }); setPreferenceMessage(""); }}><option value="zh-CN">中文</option><option value="en-US">English</option></select></label><button className="primary-button settings-save-button" type="button" onClick={savePreferences}>保存偏好</button>{preferenceMessage && <Notice tone="success">{preferenceMessage}</Notice>}</section>
    <details className="advanced-settings"><summary><span className="advanced-settings-title"><Database size={18} /><span><strong>高级设置</strong><small>数据来源与后端连接</small></span></span><ChevronRight className="advanced-settings-chevron" size={17} /></summary><div className="advanced-settings-content"><div className="setting-group"><label>数据模式</label><DirectGlassSegment value={cfg.mode} options={[{ value: "live", label: "真实 API" }, { value: "mock", label: "样本数据" }]} onChange={(mode) => { setCfg({ ...cfg, mode: mode as "live" | "mock" }); setAdvancedMessage(""); }} ariaLabel="数据模式" /></div><label>后端地址（可选）<input value={cfg.apiBase} onChange={(event) => { setCfg({ ...cfg, apiBase: event.target.value }); setAdvancedMessage(""); }} placeholder="留空 = 同源后端" /></label><button className="primary-button settings-save-button" type="button" onClick={saveAdvancedSettings}>保存高级设置</button>{advancedMessage && <Notice tone="success">{advancedMessage}</Notice>}</div></details>
  </div>;
}
