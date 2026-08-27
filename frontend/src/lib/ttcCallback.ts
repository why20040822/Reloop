export function scrubTtcCallbackHash(pathname: string, hash: string): string {
  const route = hash.split("?", 1)[0] || "#/ttc/callback";
  return `${pathname}${route}`;
}
