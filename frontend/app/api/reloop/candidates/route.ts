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

  // 私域人才库工具：联系方式是顾问跟进的刚需，直接透传。
  // 该接口只服务团队内部，RELOOP_API_TOKEN 保护后端，站点本身有访问控制。
  return {
    id: candidate.id,
    fingerprint: candidate.fingerprint,
    name: candidate.name,
    phone: candidate.phone,
    email: candidate.email,
    current_company: candidate.current_company,
    current_role: candidate.current_role,
    current_title: candidate.current_title,
    current_location: candidate.current_location,
    location: candidate.location,
    explicit_age: candidate.explicit_age,
    experience_years: candidate.experience_years,
    undergraduate_school: candidate.undergraduate_school,
    expected_salary: candidate.expected_salary,
    opportunity_intent: candidate.opportunity_intent,
    platform: candidate.platform,
    source_url: candidate.source_url,
    review_status: candidate.review_status,
    quality_score: candidate.quality_score,
    missing_fields: candidate.missing_fields,
    keywords: candidate.keywords,
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
