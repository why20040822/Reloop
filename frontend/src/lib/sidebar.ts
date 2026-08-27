const SIDEBAR_COLLAPSED_KEY = "reloop.sidebarCollapsed";

type ReadableStorage = Pick<Storage, "getItem">;
type WritableStorage = Pick<Storage, "setItem">;

function localStorageIfAvailable(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}
export function readSidebarCollapsed(storage: ReadableStorage | undefined = localStorageIfAvailable()): boolean {
  try {
    return storage?.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

export function writeSidebarCollapsed(collapsed: boolean, storage: WritableStorage | undefined = localStorageIfAvailable()): void {
  try {
    storage?.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}
