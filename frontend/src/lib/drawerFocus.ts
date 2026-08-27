export type FocusTarget = { focus: () => void; isConnected?: boolean };

export function cycleFocus<T extends FocusTarget>(targets: readonly T[], active: T | null, backwards: boolean): T | null {
  if (!targets.length) return null;
  const currentIndex = active ? targets.indexOf(active) : -1;
  const nextIndex = backwards
    ? currentIndex <= 0 ? targets.length - 1 : currentIndex - 1
    : currentIndex < 0 || currentIndex === targets.length - 1 ? 0 : currentIndex + 1;
  const next = targets[nextIndex];
  next.focus();
  return next;
}

export function restoreFocus<T extends FocusTarget>(opener: T | null, fallback: T | null): T | null {
  const target = opener && opener.isConnected !== false ? opener : fallback && fallback.isConnected !== false ? fallback : null;
  target?.focus();
  return target;
}
