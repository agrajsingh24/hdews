// Thin API client. The bearer token lives in sessionStorage (cleared when the tab closes).
export class ApiError extends Error {
    constructor(status, code, message, details) {
        super(message);
        this.status = status;
        this.code = code;
        this.details = details;
    }
}
const KEY = "hdews.session";
let session = null;
try {
    session = JSON.parse(sessionStorage.getItem(KEY) || "null");
}
catch {
    session = null;
}
export function getSession() { return session; }
export function can(p) { return !!session && session.permissions.includes(p); }
export function setSession(s) {
    session = s;
    try {
        if (s)
            sessionStorage.setItem(KEY, JSON.stringify(s));
        else
            sessionStorage.removeItem(KEY);
    }
    catch { /* storage unavailable */ }
}
export let onUnauthenticated = () => { };
export function setUnauthenticatedHandler(fn) { onUnauthenticated = fn; }
export async function api(path, opts = {}) {
    const headers = { Accept: "application/json" };
    if (opts.body !== undefined)
        headers["Content-Type"] = "application/json";
    if (session)
        headers.Authorization = `Bearer ${session.token}`;
    let res;
    try {
        res = await fetch(path, { method: opts.method || "GET", headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body) });
    }
    catch {
        throw new ApiError(0, "network", "Cannot reach the HDEWS server. Check that it is running and your connection is up.");
    }
    let data = null;
    try {
        data = await res.json();
    }
    catch { /* non-JSON */ }
    if (!res.ok) {
        const e = data?.error || {};
        if (res.status === 401 && path !== "/api/auth/login") {
            setSession(null);
            onUnauthenticated();
        }
        let msg = e.message || `Request failed (${res.status}).`;
        if (Array.isArray(e.details) && e.details.length) {
            msg += " " + e.details.map((d) => (typeof d === "string" ? d : `${d.field}: ${d.message}`)).join("; ");
        }
        throw new ApiError(res.status, e.code || "error", msg, e.details);
    }
    // Let the shell refresh derived UI (e.g. the "awaiting review" badge) after any change (HDEWS-029).
    if ((opts.method || "GET") !== "GET")
        window.dispatchEvent(new CustomEvent("hdews:mutated", { detail: { path } }));
    return data;
}
