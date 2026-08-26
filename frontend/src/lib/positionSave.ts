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
