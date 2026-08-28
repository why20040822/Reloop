import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { api, config } from "../lib/api";
import { scrubTtcCallbackHash } from "../lib/ttcCallback";
import { errorMessage } from "../components/ui";

export function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const [message, setMessage] = useState("正在完成飞书登录…");
  useEffect(() => {
    const code = new URLSearchParams(location.search).get("code");
    if (!code) { setMessage("缺少飞书授权码，请返回设置页重新登录。"); return; }
    void api.feishuLogin(code)
      .then((auth) => { config.setAuth(auth); navigate("/ttc/connect", { replace: true }); })
      .catch((error: unknown) => setMessage(errorMessage(error)));
  }, [location.search, navigate]);
  return <CallbackScreen title="飞书登录" message={message} />;
}

export function TtcConnect() {
  // 官方授权页对回调域名有白名单(TTC 前端硬编码), 未收录域名会在其页面报「授权失败」。
  // 因此不自动跳转: 默认主推零复制粘贴的扫码绑定; 官方页作为已收录域名的备选。
  const [mode, setMode] = useState<"choose" | "auto">("choose");
  const navigate = useNavigate();
  if (mode === "auto") return <TtcAutoConnect />;
  return <CallbackScreen title="连接你的人才库" message={"飞书扫码即可自动完成绑定与同步，无需复制粘贴。"} action={<div className="button-row">
    <button className="primary-button" onClick={() => setMode("auto")}>扫码绑定（推荐）</button>
    <button className="secondary-button" onClick={() => { void api.ttcLoginUrl().then(({ url }) => window.location.assign(url)).catch(() => setMode("auto")); }}>使用官方授权页</button>
    <button className="secondary-button" onClick={() => navigate("/settings")}>返回设置</button>
  </div>} />;
}

// 备用通道: 一键扫码绑定(零复制粘贴)——服务器无头浏览器打开 TTC 登录页,
// 这里轮询展示二维码截图; 用户手机飞书扫码后自动抓 Token/绑定/同步。
function TtcAutoConnect() {
  const navigate = useNavigate();
  const [qr, setQr] = useState("");
  const [status, setStatus] = useState("starting");
  const [message, setMessage] = useState("正在启动扫码绑定…");
  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const run = async () => {
      try {
        const { sid } = await api.ttcAutoLogin();
        const poll = async () => {
          if (stopped) return;
          try {
            const s = await api.ttcAutoLoginStatus(sid);
            if (stopped) return;
            setStatus(s.status);
            if (s.qr_png_b64) setQr(s.qr_png_b64);
            if (s.status === "success") {
              setMessage(`已连接${s.bound_name ? `：${s.bound_name}` : ""}，正在后台同步你的人才库。`);
              setTimeout(() => navigate("/settings", { replace: true }), 1400);
              return;
            }
            if (s.status === "pending") {
              setMessage(s.hint || "请用飞书扫描下方二维码，并在手机上点「确认授权」");
              timer = window.setTimeout(() => void poll(), 1500);
              return;
            }
            setMessage(s.error || "绑定未完成，请重试。");
          } catch (error) { if (!stopped) { setStatus("failed"); setMessage(errorMessage(error)); } }
        };
        await poll();
      } catch (error) { setStatus("failed"); setMessage(errorMessage(error)); }
    };
    void run();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [navigate]);
  return <main className="callback-screen"><div>
    <span className="brand-mark"><img className="brand-logo" src="/reloop-logo.png" alt="" /></span>
    <h1>扫码绑定人才库</h1>
    <p className="ttc-bind-notice">这个二维码是<strong>人才库（TTC）</strong>的登录授权，<strong>不是</strong> Reloop 登录码。请用手机飞书扫描，并在手机上<strong>点「确认授权」</strong>——成功后本页会自动跳转。</p>
    <p>{message}</p>
    {status === "pending" && qr ? <img className="ttc-qr" src={`data:image/png;base64,${qr}`} alt="TTC 登录二维码" /> : null}
    {status === "pending" && !qr ? <p className="hint">二维码加载中，服务器浏览器正在启动（约 15~30 秒）…</p> : null}
    <div className="button-row">
      {(status === "failed" || status === "timeout" || status === "expired") && <button className="primary-button" onClick={() => window.location.reload()}>重新发起</button>}
      <button className="secondary-button" onClick={() => navigate("/settings")}>返回设置</button>
    </div>
  </div></main>;
}

export function TtcCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const [message, setMessage] = useState("正在自动绑定并同步你的人才库…");
  useEffect(() => {
    const token = new URLSearchParams(location.search).get("token");
    history.replaceState(null, "", scrubTtcCallbackHash(window.location.pathname, window.location.hash));
    if (!token) { setMessage("未收到 TTC 登录凭证，请重新连接人才库。"); return; }
    let stopped = false;
    const bind = async () => {
      try {
        const result = await api.bindTtc(token);
        const poll = async () => {
          const status = await api.syncStatus(result.sync_id);
          if (stopped) return;
          if (status.status === "running") {
            setMessage(`正在同步人才库：${status.current || status.processed || 0}/${status.total || "…"}`);
            setTimeout(() => void poll(), 1500);
            return;
          }
          if (status.status === "done") {
            setMessage(`人才库已自动连接并同步 ${status.synced || status.current || 0} 位人才。`);
            setTimeout(() => navigate("/settings", { replace: true }), 900);
            return;
          }
          setMessage(status.error || status.message || "同步未完成，请在设置中重试。");
        };
        await poll();
      } catch (error) { if (!stopped) setMessage(errorMessage(error)); }
    };
    void bind();
    return () => { stopped = true; };
  }, [location.search, navigate]);
  return <CallbackScreen title="正在连接人才库" message={message} />;
}

function CallbackScreen({ title, message, action }: { title: string; message: string; action?: ReactNode }) {
  return <main className="callback-screen"><div><span className="brand-mark"><img className="brand-logo" src="/reloop-logo.png" alt="" /></span><h1>{title}</h1><p>{message}</p>{action}</div></main>;
}
