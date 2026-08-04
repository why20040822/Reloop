import { proxyReloop } from "../_lib";

export const dynamic = "force-dynamic";

function publicCandidate(candidate: Record<string, unknown>) {
  const experiences = Array.isArray(candidate.experiences)
    ? candidate.experiences.slice(0, 10).map((experience) => {
        if (!experience || typeof experience !== "object") return null;
        const item = experience as Record<string, unknown>;
        return {
          company: typeof item.company === "string" ? item.company : undefined,
          role: typeof item.role === "string" ? item.role : undefined,
          period: typeof item.period === "string" ? item.period : undefined,
        };
      }).filter(Boolean)
    : [];

  return {
    id: candidate.id,
    name: candidate.name,
    current_company: candidate.current_company,
    current_role: candidate.current_role,
    current_title: candidate.current_title,
    current_location: candidate.current_location,
    location: candidate.location,
    explicit_age: candidate.explicit_age,
    experience_years: candidate.experience_years,
    undergraduate_school: candidate.undergraduate_school,
    score: candidate.score,
    jd_score: candidate.jd_score,
    jd_recommendation: candidate.jd_recommendation,
    recommendation: candidate.recommendation,
    collected_at: candidate.collected_at,
    updated_at: candidate.updated_at,
    experiences,
  };
}

export async function GET(request: Request) {
  const query = new URL(request.url).searchParams.get("q")?.trim();
  const pathname = query ? `/api/candidates?q=${encodeURIComponent(query)}` : "/api/candidates";
  const response = await proxyReloop(pathname);
  if (!response.ok) return response;

  const payload = await response.json().catch(() => null);
  if (!Array.isArray(payload)) return Response.json(payload, { status: response.status });
  return Response.json(payload.map((candidate) => (
    candidate && typeof candidate === "object" ? publicCandidate(candidate as Record<string, unknown>) : candidate
  )), { status: response.status });
}
