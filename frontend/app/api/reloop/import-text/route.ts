import { proxyReloop } from "../_lib";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  // 走 v2 统一流水线：解析 → outbox（持久化）→ worker 投递云端精品库
  // v1 /api/import-text 只写本地 SQLite，面板读云端，会形成"录入即失踪"
  let text = "";
  let title = "前端录入";
  try {
    const parsed = await request.json();
    text = typeof parsed.text === "string" ? parsed.text : "";
    if (typeof parsed.title === "string" && parsed.title.trim()) title = parsed.title.trim();
  } catch {
    return Response.json({ ok: false, detail: "请求体必须是 JSON" }, { status: 400 });
  }
  if (text.trim().length < 10) {
    return Response.json({ ok: false, detail: "内容太短（至少 10 字）" }, { status: 400 });
  }
  return proxyReloop("/api/ingest-v2/text", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, title, source_url: "", dry_run: false }),
  });
}
