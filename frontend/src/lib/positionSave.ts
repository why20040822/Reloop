import type { Position } from "./api";

export type PositionSaveResult = {
  position: Position;
  positions: Position[] | null;
  refreshError: unknown | null;
};

export async function saveThenRefreshPosition(save: () => Promise<Position>, refresh: () => Promise<Position[]>): Promise<PositionSaveResult> {
  const position = await save();
  try {
    return { position, positions: await refresh(), refreshError: null };
  } catch (refreshError) {
    return { position, positions: null, refreshError };
  }
}

function identity(position: Pick<Position, "position_name" | "company_name">) {
  return `${position.company_name?.trim() || ""}\u0000${position.position_name.trim()}`;
}

export function mergeSavedPositionFallback(
  previous: Position[],
  saved: Position,
  replacedPositionId?: number,
): Position[] {
  const savedIdentity = identity(saved);
  return [
    saved,
    ...previous.filter((position) => (
      position.id !== saved.id
      && position.id !== replacedPositionId
      && identity(position) !== savedIdentity
    )),
  ];
}
