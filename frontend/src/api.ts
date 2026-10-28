// Thin API client. The bearer token lives in sessionStorage (cleared when the tab closes).

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) { super(message); }
}

const KEY = "hdews.session";

export interface User { id: string; username: string; display_name: string; role: string }
export interface Session { token: string; user: User; permissions: string[] }

let session: Session | null = null;
try { session = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { session = null; }

export function getSession(): Session | null { return session; }
export function can(p: string): boolean { return !!session && session.permissions.includes(p); }
export function setSession(s: Session | null): void {
  session = s;
  try { if (s) sessionStorage.setItem(KEY, JSON.stringify(s)); else sessionStorage.removeItem(KEY); } catch { /* storage unavailable */ }
}

export let onUnauthenticated: () => void = () => {};
export function setUnauthenticatedHandler(fn: () => void): void { onUnauthenticated = fn; }

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (session) headers.Authorization = `Bearer ${session.token}`;
  let res: Response;
  try {
    res = await fetch(path, { method: opts.method || "GET", headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body) });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the HDEWS server. Check that it is running and your connection is up.");
  }
  let data: any = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    const e = data?.error || {};
    if (res.status === 401 && path !== "/api/auth/login") { setSession(null); onUnauthenticated(); }
    let msg: string = e.message || `Request failed (${res.status}).`;
    if (Array.isArray(e.details) && e.details.length) {
      msg += " " + e.details.map((d: any) => (typeof d === "string" ? d : `${d.field}: ${d.message}`)).join("; ");
    }
    throw new ApiError(res.status, e.code || "error", msg, e.details);
  }
  return data as T;
}
