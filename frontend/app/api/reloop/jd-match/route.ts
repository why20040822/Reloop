import { proxyReloop } from "../_lib";

export const dynamic = "force-dynamic";

const MAX_JD_TEXT = 20000;

export async function POST(request: Request) {
  let body: { jd_text?: string; limit?: number; pool_size?: number; llm_pool_size?: number };
  try {
    body = await request.json();
  } catch {
    return Response.json({ ok: false, detail: "请求体必须是 JSON" }, { status: 400 });
  }

  const jdText = typeof body.jd_text === "string" ? body.jd_text.trim() : "";
  if (jdText.length < 5 || jdText.length > MAX_JD_TEXT) {
    return Response.json({ ok: false, detail: "jd_text 长度需在 5-20000 字之间" }, { status: 400 });
  }

  return proxyReloop("/api/jd-match", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jd_text: jdText,
      limit: body.limit ?? 5,
      pool_size: body.pool_size ?? 100,
      llm_pool_size: body.llm_pool_size ?? 20,
    }),
  });
}
