export async function apiFetch(
  path: string,
  options?: RequestInit
): Promise<Response> {
  const baseUrl = import.meta.env.VITE_BRAIN_URL as string | undefined;
  if (!baseUrl) {
    throw new Error("VITE_BRAIN_URL not set");
  }

  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  if (options?.headers) {
    new Headers(options.headers).forEach((value, key) => {
      headers.set(key, value);
    });
  }

  const url = `${baseUrl}${path}`;
  return fetch(url, {
    ...options,
    credentials: options?.credentials ?? "include",
    headers,
  });
}

export async function apiJson<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await apiFetch(path, options);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}
