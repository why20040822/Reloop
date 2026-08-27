import type { JDAnalysis, Position } from "./api";

type PositionSavePayload = Pick<Position, "position_name" | "company_name" | "jd_text" | "jd_analysis">;

export function findPositionById(positions: Position[], positionId: number | null) {
  return positions.find((position) => position.id === positionId);
}

export function requiresJdParser(position?: Pick<Position, "jd_analysis"> | null) {
  return !Boolean(position?.jd_analysis);
}

export function buildReviewedPositionPayload(position: Pick<Position, "position_name"> | undefined, analysis: JDAnalysis, jdText: string): PositionSavePayload {
  const companyName = analysis.company_name?.trim() || null;
  return {
    position_name: position?.position_name || analysis.title,
    company_name: companyName,
    jd_text: jdText,
    jd_analysis: { ...analysis, company_name: companyName },
  };
}

export function buildManualPositionPayload(companyName: string, positionName: string, jdText: string): PositionSavePayload {
  return {
    position_name: positionName.trim(),
    company_name: companyName.trim() || null,
    jd_text: jdText.trim(),
  };
}
