/**
 * Pure validation logic for extension page capture.
 * Keeps platform-specific assertions testable without browser APIs.
 */

export function validatePayload(payload) {
  const text = payload.text || '';
  const sections = (payload.structured_data && Array.isArray(payload.structured_data.sections))
    ? payload.structured_data.sections
    : [];
  const headings = new Set(sections.map(s => s.heading).filter(Boolean));

  const checks = {
    hasText: text.length > 80,
    hasStructuredData: sections.length > 0,
    platform: payload.platform || '',
  };

  if (checks.platform === 'boss') {
    checks.hasWorkExperience = headings.has('工作经历');
    checks.hasEducationExperience = headings.has('教育经历');
  } else if (checks.platform === 'maimai' || checks.platform === 'liepin') {
    checks.hasCandidateLinks = Array.isArray(payload.links) && payload.links.length > 0;
  }

  checks.ok = checks.hasText && checks.hasStructuredData;
  return checks;
}
