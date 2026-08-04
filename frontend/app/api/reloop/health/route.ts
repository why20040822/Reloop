import { proxyReloop } from "../_lib";

export const dynamic = "force-dynamic";

export async function GET() {
  return proxyReloop("/api/health");
}
