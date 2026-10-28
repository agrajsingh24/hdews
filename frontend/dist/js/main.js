import { api, getSession, setSession, setUnauthenticatedHandler, can } from "./api.js";
import { h, loading, toast } from "./dom.js";
import { errorBox } from "./ui.js";
import { overviewPage } from "./pages/overview.js";
import { sitesPage, sitePage, assessmentPage, mapPage } from "./pages/sites.js";
import { alertsPage, alertPage } from "./pages/alerts.js";
import { simulatorPage } from "./pages/simulator.js";
import { incidentsPage, sourcesPage, evaluationPage, auditPage, settingsPage } from "./pages/misc.js";
const ROUTES = [
    { pattern: /^\/?$/, page: overviewPage, nav: "overview" },
    { pattern: /^\/map$/, page: mapPage, nav: "map" },
    { pattern: /^\/sites$/, page: sitesPage, nav: "sites" },
    { pattern: /^\/sites\/([\w-]+)$/, page: sitePage, nav: "sites" },
    { pattern: /^\/assessments\/([\w-]+)$/, page: assessmentPage, nav: "sites" },
    { pattern: /^\/alerts$/, page: alertsPage, nav: "alerts" },
    { pattern: /^\/alerts\/([\w-]+)$/, page: alertPage, nav: "alerts" },
    { pattern: /^\/simulator$/, page: simulatorPage, nav: "simulator" },
    { pattern: /^\/incidents$/, page: incidentsPage, nav: "incidents" },
    { pattern: /^\/sources$/, page: sourcesPage, nav: "sources" },
    { pattern: /^\/evaluation$/, page: evaluationPage, nav: "evaluation" },
    { pattern: /^\/audit$/, page: auditPage, nav: "audit" },
    { pattern: /^\/settings$/, page: settingsPage, nav: "settings" },
];
const NAV = [
    ["overview", "#/", "Overview"], ["map", "#/map", "Live map"], ["sites", "#/sites", "Monitoring sites"],
    ["alerts", "#/alerts", "Candidate alerts"], ["simulator", "#/simulator", "Scenario simulator"],
    ["incidents", "#/incidents", "Historical events"], ["sources", "#/sources", "Data sources"],
    ["evaluation", "#/evaluation", "Model & evaluation"], ["audit", "#/audit", "Audit log"], ["settings", "#/settings", "Settings"],
];
const app = document.getElementById("app");
let cleanup;
let meta = null;
let badgeTimer;
async function loginView() {
    if (badgeTimer)
        clearInterval(badgeTimer);
    try {
        meta = meta || await api("/api/meta");
    }
    catch { /* shown below */ }
    const err = h("p", { class: "form-error", role: "alert" });
    const form = h("form", { class: "login-form", onsubmit: async (e) => {
            e.preventDefault();
            const fd = new FormData(form);
            err.textContent = "";
            try {
                const r = await api("/api/auth/login", { method: "POST", body: { username: String(fd.get("username")), password: String(fd.get("password")) } });
                setSession({ token: r.token, user: r.user, permissions: [] });
                const me = await api("/api/auth/me");
                setSession({ token: r.token, user: me.user, permissions: me.permissions });
                shell();
            }
            catch (ex) {
                err.textContent = ex.message;
            }
        } }, h("label", { class: "field" }, h("span", null, "Username"), h("input", { name: "username", autocomplete: "username", required: true, autofocus: true })), h("label", { class: "field" }, h("span", null, "Password"), h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })), err, h("button", { class: "btn btn-primary", type: "submit" }, "Sign in"));
    app.replaceChildren(h("main", { class: "login" }, h("div", { class: "login-card" }, h("div", { class: "brand brand-lg" }, h("span", { class: "brand-mark", "aria-hidden": "true" }), h("span", null, "HDEWS")), h("h1", null, "Himalayan Disaster Early Warning System"), h("p", { class: "muted" }, "Evidence-first decision support for landslide and flash-flood review. Research prototype."), form, meta?.demo_login_hint ? h("div", { class: "callout" }, h("strong", null, "Demo sign-in. "), meta.demo_login_hint, h("ul", { class: "plain small" }, h("li", null, h("strong", null, "reviewer"), " acknowledges, acts on and resolves alerts"), h("li", null, h("strong", null, "analyst"), " runs the simulator and re-assessments"), h("li", null, h("strong", null, "admin"), " everything, including thresholds"), h("li", null, h("strong", null, "viewer"), " read-only"))) : null, h("p", { class: "safety small" }, meta?.safety_notice || "Prototype — not an official warning service."))));
}
function navLink(key, href, label) {
    return h("a", { href, "data-nav": key }, h("span", null, label), key === "alerts" ? h("span", { class: "nav-badge", id: "alert-badge", hidden: true }) : null);
}
async function refreshBadge() {
    try {
        const r = await api("/api/alerts?status=REVIEW_REQUIRED&limit=1");
        const b = document.getElementById("alert-badge");
        if (b) {
            b.hidden = r.total === 0;
            b.textContent = String(r.total);
            b.title = `${r.total} awaiting review`;
        }
    }
    catch { /* ignore */ }
}
function shell() {
    const s = getSession();
    const nav = h("nav", { class: "sidenav", id: "sidenav", "aria-label": "Main" }, NAV.map(([k, href, label]) => navLink(k, href, label)));
    const menuBtn = h("button", { class: "btn btn-icon menu-btn", type: "button", "aria-controls": "sidenav", "aria-expanded": "false", "aria-label": "Menu",
        onclick: () => { const open = document.body.classList.toggle("nav-open"); menuBtn.setAttribute("aria-expanded", String(open)); } }, "☰");
    app.replaceChildren(h("div", { class: "proto-strip", role: "note" }, h("strong", null, "Prototype."), " Simulated data. Not an official warning service; candidate alerts are for authorised review only."), h("div", { class: "layout" }, h("aside", { class: "rail" }, h("div", { class: "rail-top" }, h("a", { class: "brand", href: "#/" }, h("span", { class: "brand-mark", "aria-hidden": "true" }), h("span", null, "HDEWS")), menuBtn), nav, h("div", { class: "rail-user" }, h("div", null, h("strong", null, s.user.display_name), h("div", { class: "small" }, `Role: ${s.user.role}`)), h("button", { class: "btn btn-small btn-ghost", type: "button", onclick: async () => {
            try {
                await api("/api/auth/logout", { method: "POST" });
            }
            catch { /* ignore */ }
            setSession(null);
            location.hash = "#/";
            loginView();
        } }, "Sign out"))), h("main", { id: "main", class: "main", tabindex: "-1" })), h("div", { id: "toasts", class: "toasts", "aria-live": "polite" }));
    refreshBadge();
    if (badgeTimer)
        clearInterval(badgeTimer);
    badgeTimer = window.setInterval(refreshBadge, 45000);
    route();
}
async function route() {
    if (!getSession()) {
        loginView();
        return;
    }
    const main = document.getElementById("main");
    if (!main) {
        shell();
        return;
    }
    if (typeof cleanup === "function")
        cleanup();
    cleanup = undefined;
    document.body.classList.remove("nav-open");
    const [path, query] = (location.hash.slice(1) || "/").split("?");
    const params = new URLSearchParams(query || "");
    const def = ROUTES.find(r => r.pattern.test(path));
    document.querySelectorAll("[data-nav]").forEach(a => a.toggleAttribute("aria-current", a.getAttribute("data-nav") === def?.nav));
    if (!def) {
        main.replaceChildren(errorBox({ message: `There is no page at “${path}”.` }));
        return;
    }
    if (def.nav === "simulator" && !can("read"))
        return;
    main.replaceChildren(loading());
    const m = path.match(def.pattern);
    const run = async () => {
        try {
            cleanup = await def.page(main, m[1] ?? params);
            const title = main.querySelector("h1")?.textContent;
            document.title = title ? `${title} — HDEWS prototype` : "HDEWS prototype";
            refreshBadge();
        }
        catch (err) {
            main.replaceChildren(errorBox(err, run));
        }
    };
    await run();
    main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
}
setUnauthenticatedHandler(() => { toast("Your session ended. Sign in again.", "error"); loginView(); });
window.addEventListener("hashchange", route);
if (getSession())
    shell();
else
    loginView();
