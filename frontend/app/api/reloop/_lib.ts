const DEFAULT_RELOOP_API_BASE_URL = "http://127.0.0.1:18765";

export function reloopApiUrl(pathname: string): string {
  const baseUrl = process.env.RELOOP_API_BASE_URL || DEFAULT_RELOOP_API_BASE_URL;
  return `${baseUrl.replace(/\/$/, "")}${pathname}`;
}

export function reloopHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  const token = process.env.RELOOP_API_TOKEN?.trim();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

export async function proxyReloop(pathname: string, init?: RequestInit): Promise<Response> {
  try {
    const response = await fetch(reloopApiUrl(pathname), {
      ...init,
      headers: reloopHeaders(init?.headers),
      cache: "no-store",
    });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") || "application/json" },
    });
  } catch (error) {
    return Response.json(
      {
        ok: false,
        detail: `Reloop 后端暂不可用：${error instanceof Error ? error.message : "连接失败"}`,
      },
      { status: 502 },
    );
  }
}
