import type { JDAnalysis, Position } from "./api";

export type JDAnalysisDraft = { [K in keyof JDAnalysis]: string };

const listFields = new Set<keyof JDAnalysis>([
  "responsibilities",
  "required_skills",
  "preferred_skills",
  "industry_keywords",
  "language_requirements",
]);

function listToDraft(values: string[]) {
  return values.join("\n");
}

function draftToList(value: string) {
  const seen = new Set<string>();
  return value.split("\n").map((item) => item.trim()).filter((item) => {
    if (!item || seen.has(item)) return false;
    seen.add(item);
    return true;
  });
}

export function analysisToDraft(analysis: JDAnalysis): JDAnalysisDraft {
  return Object.fromEntries(Object.entries(analysis).map(([key, value]) => [
    key,
    listFields.has(key as keyof JDAnalysis) ? listToDraft(value as string[]) : value || "",
  ])) as JDAnalysisDraft;
}

export function draftToAnalysis(draft: JDAnalysisDraft): JDAnalysis {
  return Object.fromEntries(Object.entries(draft).map(([key, value]) => [
    key, listFields.has(key as keyof JDAnalysis) ? draftToList(value) : key === "company_name" ? value.trim() || null : value.trim(),
  ])) as JDAnalysis;
}

export function formatPositionLabel(position: Pick<Position, "company_name" | "position_name">) {
  const companyName = position.company_name?.trim();
  return companyName ? `${companyName} - ${position.position_name}` : position.position_name;
}

export function positionHasParsedJd(position?: Pick<Position, "jd_analysis"> | null) {
  return Boolean(position?.jd_analysis);
}
