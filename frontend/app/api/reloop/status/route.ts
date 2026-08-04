import { reloopApiUrl, reloopHeaders } from "../_lib";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const [healthResponse, candidatesResponse] = await Promise.all([
      fetch(reloopApiUrl("/api/health"), { headers: reloopHeaders(), cache: "no-store" }),
      fetch(reloopApiUrl("/api/candidates"), { headers: reloopHeaders(), cache: "no-store" }),
    ]);
    const health = await healthResponse.json().catch(() => ({}));
    const candidates = await candidatesResponse.json().catch(() => []);
    const ok = healthResponse.ok && candidatesResponse.ok && health?.ok !== false;
    return Response.json({
      ok,
      service: health.service || "reloop",
      version: health.version || null,
      candidateCount: Array.isArray(candidates) ? candidates.length : 0,
    }, { status: ok ? 200 : 502 });
  } catch (error) {
    return Response.json(
      { ok: false, detail: `Reloop 后端暂不可用：${error instanceof Error ? error.message : "连接失败"}` },
      { status: 502 },
    );
  }
}
