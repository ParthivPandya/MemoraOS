import "server-only";

const BASE = (process.env.MEMORAOS_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const KEY = process.env.MEMORAOS_API_KEY ?? "";
export const USER_ID = process.env.MEMORAOS_USER_ID ?? "user_001";

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

/** Server-side call to the MemoraOS REST API. The API key never reaches the browser. */
export async function api<T>(path: string, init?: { method?: string; body?: unknown; query?: Record<string, string> }): Promise<ApiResult<T>> {
  const url = new URL(BASE + path);
  for (const [k, v] of Object.entries(init?.query ?? {})) url.searchParams.set(k, v);
  try {
    const res = await fetch(url, {
      method: init?.method ?? "GET",
      headers: { "Content-Type": "application/json", ...(KEY ? { Authorization: `Bearer ${KEY}` } : {}) },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) return { ok: false, error: `API ${res.status}: ${JSON.stringify((data as { detail?: unknown } | null)?.detail ?? data)}` };
    return { ok: true, data: data as T };
  } catch (e) {
    return { ok: false, error: `Cannot reach the MemoraOS API at ${BASE} (${(e as Error).message}). Start it with: memoraos serve` };
  }
}

export const userQuery = { user_id: USER_ID };
