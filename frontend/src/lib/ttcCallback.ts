const callbackOperations = new Map<string, Promise<unknown>>();

export function scrubCallbackHash(pathname: string, hash: string): string {
  const route = hash.split("?", 1)[0] || "#/ttc/callback";
  return `${pathname}${route}`;
}

export function runCallbackOnce<T>(key: string, action: () => Promise<T>): Promise<T> {
  const existing = callbackOperations.get(key);
  if (existing) return existing as Promise<T>;
  const operation = Promise.resolve().then(action);
  callbackOperations.set(key, operation);
  const release = () => {
    if (callbackOperations.get(key) === operation) callbackOperations.delete(key);
  };
  void operation.then(release, release);
  return operation;
}
