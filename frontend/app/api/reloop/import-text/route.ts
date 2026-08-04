import { proxyReloop } from "../_lib";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = await request.text();
  return proxyReloop("/api/import-text", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  });
}
