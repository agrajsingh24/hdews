// HDEWS end-to-end scenarios (Playwright, Chromium). Run via: python e2e/run_e2e.py
// Usage: node e2e/scenarios.js <phase: main|restart|production>   (env: BASE, PASSWORD, INGEST_KEY, SHOTS)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const BASE = process.env.BASE, PASSWORD = process.env.PASSWORD, KEY = process.env.INGEST_KEY, SHOTS = process.env.SHOTS;
const phase = process.argv[2];
const results = [];

function check(scn, name, ok, detail = "") { results.at(-1).checks.push({ name, ok: !!ok, detail: String(detail).slice(0, 300) }); if (!ok) results.at(-1).ok = false; }

async function session(browser, viewport = { width: 1366, height: 900 }) {
  const ctx = await browser.newContext({ viewport, timezoneId: "Europe/London" });  // UI must still show IST
  const page = await ctx.newPage();
  page.problems = [];
  // Chromium echoes every 4xx/5xx response as a console error; responses are checked individually below,
  // so only other console errors are recorded here.
  page.on("console", m => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) page.problems.push("console: " + m.text()); });
  page.on("pageerror", e => page.problems.push("pageerror: " + e.message));
  page.on("response", r => {
    const u = r.url();
    if (!u.startsWith(BASE)) return;
    if (r.status() >= 500) page.problems.push(`HTTP ${r.status()} ${r.request().method()} ${u}`);
    if (r.status() >= 400 && !(page.allow4xx || []).some(p => u.includes(p))) page.problems.push(`HTTP ${r.status()} ${r.request().method()} ${u}`);
  });
  return { ctx, page };
}

async function login(page, user) {
  await page.goto(BASE + "/");
  await page.waitForSelector(".login-card");
  await page.fill("input[name=username]", user);
  await page.fill("input[name=password]", PASSWORD);
  await page.click("button[type=submit]");
  await page.waitForSelector(".rail");
}

async function token(page) { return page.evaluate(() => JSON.parse(sessionStorage.getItem("hdews.session")).token); }
async function apiCall(page, method, path, body) {
  return page.evaluate(async ([m, p, b]) => {
    const t = JSON.parse(sessionStorage.getItem("hdews.session")).token;
    const r = await fetch(p, { method: m, headers: { Authorization: "Bearer " + t, "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
    let j = null; try { j = await r.json(); } catch {}
    return { status: r.status, body: j };
  }, [method, path, body]);
}
async function go(page, hash, selector) { await page.goto(BASE + "/" + hash); await page.waitForSelector(selector, { timeout: 15000 }); await page.waitForTimeout(250); }
async function shot(page, name) { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); }
async function badge(page) { return page.evaluate(() => { const b = document.getElementById("alert-badge"); return b && !b.hidden ? Number(b.textContent) : 0; }); }
async function noHorizontalOverflow(page) { return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1); }

async function a11yAudit(page) {
  return page.evaluate(() => {
    const issues = [];
    const name = el => (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || "").trim();
    document.querySelectorAll("button, a[href]").forEach(el => { if (!name(el)) issues.push("unnamed " + el.tagName + " " + el.outerHTML.slice(0, 80)); });
    document.querySelectorAll("input:not([type=hidden]), select, textarea").forEach(el => {
      const labelled = el.closest("label") || el.getAttribute("aria-label") || (el.id && document.querySelector(`label[for="${el.id}"]`));
      if (!labelled) issues.push("unlabelled " + el.outerHTML.slice(0, 80));
    });
    document.querySelectorAll("svg[role=img]").forEach(el => { if (!el.getAttribute("aria-label")) issues.push("svg without label"); });
    return issues;
  });
}

async function scenario(name, fn, browser) {
  results.push({ scenario: name, ok: true, checks: [] });
  const { ctx, page } = await session(browser);
  try { await fn(page, ctx); }
  catch (e) { check(name, "scenario completed without exception", false, e.message.split("\n")[0]); await shot(page, "FAIL-" + name.replace(/\W+/g, "_")); }
  check(name, "no console errors, page errors, 5xx or unexpected 4xx", page.problems.length === 0, page.problems.join(" | "));
  await ctx.close();
}

// ------------------------------------------------------------------ main phase
async function A(page) {
  await login(page, "analyst");
  await page.waitForSelector(".grid-overview");
  check("A", "overview shows data mode Simulated", await page.locator(".page-head .origin-SIMULATED").count() > 0);
  check("A", "site matrix lists 6 sites", await page.locator(".matrix tbody tr").count() === 6);
  check("A", "prototype strip visible", await page.locator(".proto-strip").isVisible());
  const t = await page.locator("time").first();
  const iso = await t.getAttribute("datetime"), text = await t.textContent();
  const ist = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));
  check("A", "times rendered in IST regardless of browser timezone", text.includes(ist) && text.endsWith("IST"), `${iso} -> ${text}`);
  await go(page, "#/map", ".map-svg .site");
  check("A", "map renders 6 site markers", await page.locator(".map-svg .site").count() === 6);
  // Keyboard: focus a marker and open it with Enter.
  await page.locator(".map-svg .site").first().focus();
  await page.keyboard.press("Enter");
  await page.waitForSelector(".drawer .btn-primary");
  check("A", "keyboard Enter on marker opens site drawer", await page.locator(".drawer h2").count() > 0);
  await page.click(".drawer-head button");
  check("A", "drawer closes", (await page.locator(".drawer h2").first().textContent()).includes("Select a site"));
  await page.click(".map-zoom button[aria-label='Zoom in']");
  check("A", "zoom control works", await page.locator(".map-svg .site").count() === 6);
  await go(page, "#/sites/SNP-05", ".assess");
  check("A", "site shows 4 sensor cards", await page.locator(".sensor").count() === 4);
  const units = await page.locator(".sensor .unit").allTextContents();
  check("A", "sensor units shown", ["mm", "% VWC", "m"].every(u => units.some(x => x.trim() === u)), units.join(","));
  check("A", "two hazard risk cards with tier and reliability", await page.locator(".assess .risk-tier").count() >= 2 && await page.locator(".assess .risk-rel").count() >= 2);
  check("A", "four trend charts", await page.locator("svg.chart").count() === 4);
  const issues = await a11yAudit(page);
  check("A", "accessibility: controls named, inputs labelled, charts labelled", issues.length === 0, issues.join("; "));
  await shot(page, "A-site");
}

async function B(page, ctx) {
  await login(page, "analyst");
  await go(page, "#/simulator?site=SNP-05", ".preset-list");
  await page.check("input[value=rising_landslide_indicators]");
  await page.click("text=Apply scenario and re-assess");
  await page.waitForSelector(".sim-result table");
  const res = await page.locator(".sim-result").textContent();
  check("B", "backend returns HIGH landslide", res.includes("Landslide") && res.includes("High"), res.slice(0, 200));
  const href = await page.locator(".sim-result .callout-warn a").first().getAttribute("href");
  check("B", "candidate alert linked from simulator", !!href, href);
  const obs = await apiCall(page, "GET", "/api/sites/SNP-05/observations?hours=1");
  check("B", "new observations are SIMULATED", obs.body.series.every(s => s.points.every(p => p.o === "SIMULATED")));
  await page.click("text=Sign out");
  await login(page, "reviewer");
  await page.waitForFunction(() => { const b = document.getElementById("alert-badge"); return b && !b.hidden; }, null, { timeout: 10000 });
  const before = await badge(page);
  await go(page, href, ".stepper");
  check("B", "alert page shows not-an-official-warning notice", (await page.locator(".demo-notice").textContent()).includes("Not an official warning"));
  check("B", "evidence card present", await page.locator(".assess .factors tbody tr").count() === 4);
  check("B", "reviewer sees Acknowledge", await page.locator('.alert-controls button:has-text("Acknowledge")').count() === 1);
  await page.click('.alert-controls button:has-text("Acknowledge")');
  check("B", "dialog focuses first field", await page.evaluate(() => document.activeElement && document.activeElement.tagName === "TEXTAREA"));
  await page.keyboard.press("Escape");
  // The dialog's "close" event fires asynchronously after Escape; wait (bounded) for the removal.
  const removed = await page.waitForFunction(() => !document.querySelector("dialog"), null, { timeout: 2000 }).then(() => true, () => false);
  check("B", "Escape removes the dialog from the page", removed);
  check("B", "Escape cancels dialog without acting", (await apiCall(page, "GET", "/api/alerts/" + href.split("/").pop())).body.alert.status === "REVIEW_REQUIRED");
  await page.click('.alert-controls button:has-text("Acknowledge")');
  await page.fill("dialog textarea[name=notes]", "Reviewing evidence");
  await page.click("dialog button[type=submit]");
  await page.waitForSelector('.alert-controls button:has-text("Record action")');
  await page.waitForTimeout(400);
  check("B", "sidebar badge updates after acknowledging (no stale count)", await badge(page) === before - 1, `before ${before}, after ${await badge(page)}`);
  check("B", "exactly one toast per action", await page.locator(".toast").count() === 1);
  await page.click('.alert-controls button:has-text("Record action")');
  await page.fill("dialog input[name=assignee]", "Field team 2");
  await page.fill("dialog textarea[name=notes]", "Inspect the slope above the road");
  await page.click("dialog button[type=submit]");
  await page.waitForSelector(".stepper li.current >> text=Action assigned");
  await page.click('.alert-controls button:has-text("Resolve")');
  await page.click("dialog button[type=submit]");  // empty reason: browser validation blocks submit
  check("B", "resolve without reason is blocked", await page.locator("dialog[open]").count() === 1);
  await page.fill("dialog textarea[name=reason]", "Simulated scenario, demo exercise complete");
  await page.click("dialog button[type=submit]");
  await page.waitForSelector(".stepper li.current >> text=Resolved");
  const api = await apiCall(page, "GET", "/api/alerts/" + href.split("/").pop());
  check("B", "UI status matches API status", api.body.alert.status === "RESOLVED");
  check("B", "action log shows acknowledge, field verification, resolve in order",
    JSON.stringify(api.body.actions.map(a => a.action_type)) === JSON.stringify(["acknowledge", "field_verification", "resolve"]));
  await go(page, "#/audit", "table.audit");
  await page.click("text=Verify hash chain");
  await page.waitForSelector("text=Chain intact");
  check("B", "audit chain verifies in UI", true);
  await shot(page, "B-audit");
  results.at(-1).alert = href;
}

async function C(page) {
  await login(page, "analyst");
  const r1 = await apiCall(page, "POST", "/api/demo/scenario", { site_ids: ["TLW-02"], preset: "rapid_river_rise" });
  check("C", "flash-flood scenario HIGH", r1.body.assessments.some(a => a.hazard === "flash_flood" && a.risk_tier === "HIGH"));
  await apiCall(page, "POST", "/api/demo/scenario", { site_ids: ["TLW-02"], preset: "rapid_river_rise" });
  const open = await apiCall(page, "GET", "/api/alerts?status=open&site_id=TLW-02");
  check("C", "re-applying scenario does not duplicate the alert", open.body.items.filter(a => a.kind === "HAZARD").length === 1);
  const aid = open.body.items[0].id;
  await go(page, "#/alerts/" + aid, ".assess");
  const ev = await page.locator(".assess h3").first().textContent();
  check("C", "evidence refers to flash flood", ev.includes("Flash flood"), ev);
  const factors = await page.locator(".assess .factors th[scope=row]").allTextContents();
  check("C", "flood-specific features shown", factors.some(f => f.includes("River stage")) && !factors.some(f => f.includes("Soil")), factors.join("|"));
  await go(page, "#/alerts", ".alerts-table");
  check("C", "alerts list renders open alerts", await page.locator(".alerts-table tbody tr").count() >= 1);
}

async function D(page, ctx) {
  await login(page, "analyst");
  await go(page, "#/simulator?site=SNP-05", ".preset-list");
  await page.check("input[value=sensor_outage_adverse_weather]");
  await page.click("text=Apply scenario and re-assess");
  await page.waitForSelector(".sim-result table");
  await go(page, "#/sites/SNP-05", ".assess");
  const rel = await page.locator(".assess .rel-text").allTextContents();
  check("D", "reliability shown as poor", rel.every(t => t.trim() === "poor"), rel.join(","));
  const offline = await page.locator(".sensor-OFFLINE").count();
  check("D", "two sensors shown Offline", offline === 2, offline);
  check("D", "offline values marked not current", await page.locator(".sensor-OFFLINE .stale-flag").count() === 2);
  const tiers = await page.locator(".assess .risk-tier").allTextContents();
  check("D", "no LOW tier during outage; underestimate disclosed", !tiers.some(t => t.startsWith("Low")) && tiers.some(t => t.includes("+") || t.includes("Insufficient")), tiers.join(","));
  await go(page, "#/alerts?kind=DATA_QUALITY", ".alerts-table");
  check("D", "data-gap alerts listed separately from hazard alerts", await page.locator(".alerts-table .kind-DATA_QUALITY").count() >= 1 && await page.locator(".alerts-table .kind-HAZARD").count() === 0);
  // Restore: real readings for the offline sensors arrive through the gateway.
  const now = Date.now(); const readings = [];
  for (let i = 0; i < 6; i++) {
    const t = new Date(Math.floor((now - i * 900e3) / 1000) * 1000).toISOString().replace(".000Z", "Z");
    readings.push({ sensor_id: "SNP-05-SOIL", observed_at: t, value: 30 }, { sensor_id: "SNP-05-RIVER", observed_at: t, value: 1.2 });
  }
  readings.push({ sensor_id: "SNP-05-EXT", observed_at: new Date(Math.floor(now / 1000) * 1000).toISOString().replace(".000Z", "Z"), value: 14 },
                { sensor_id: "SNP-05-EXT", observed_at: new Date(Math.floor((now - 86400e3) / 1000) * 1000).toISOString().replace(".000Z", "Z"), value: 13.9 });
  const ing = await ctx.request.post(BASE + "/api/ingestion/FIELD-GATEWAY-01", { data: { readings }, headers: { "X-HDEWS-Ingest-Key": KEY } });
  check("D", "gateway readings accepted", ing.status() === 202, await ing.text());
  await go(page, "#/sites/SNP-05", ".assess");
  const rel2 = await page.locator(".assess .rel-text").allTextContents();
  check("D", "reliability recovers only after valid readings arrive", rel2.every(t => t.trim() !== "poor"), rel2.join(","));
  check("D", "no sensors offline after recovery", await page.locator(".sensor-OFFLINE").count() === 0);
  const soilCard = page.locator(".sensor", { hasText: "SNP-05-SOIL" });
  check("D", "card labels the latest (gateway) reading as Observed, not Simulated",
    await soilCard.locator("dd .origin-OBSERVED").count() === 1);
  // HDEWS-033: observed and simulated readings are drawn as separate series, never one joined line.
  const riverPaths = await page.locator("figure.chart-wrap", { hasText: "River stage" }).locator("path.series").evaluateAll(
    ps => ps.map(p => p.getAttribute("data-origin")));
  check("D", "chart draws observed and simulated readings as separate lines",
    riverPaths.includes("OBSERVED") && riverPaths.includes("SIMULATED") && new Set(riverPaths).size === riverPaths.length, riverPaths.join(","));
  const notes = await page.locator(".assess .notes").allTextContents();
  check("D", "mixed-origin readings disclosed in reliability notes", notes.some(n => n.includes("mixed origins")), notes.join(" | ").slice(0, 200));
  await shot(page, "D-recovered");
  // HDEWS-036: a complete blackout (rain gauge included) at another site must still reach the review queue.
  const blackout = await apiCall(page, "POST", "/api/demo/scenario", { site_ids: ["TLW-02"], preset: "rapid_river_rise",
    overrides: { offline_sensors: ["rain_gauge", "river_stage"], outage_minutes: 420 } });
  check("D", "total blackout assessed as insufficient data", blackout.status === 200 &&
    blackout.body.assessments.every(a => a.risk_tier === "INSUFFICIENT_DATA"), JSON.stringify(blackout.body.assessments || blackout.body));
  await go(page, "#/alerts?kind=DATA_QUALITY", ".alerts-table");
  const rows = await page.locator(".alerts-table tbody tr", { hasText: "Tilwara" }).allTextContents();
  check("D", "total blackout raises a data-gap alert in the UI", rows.length === 1 && rows[0].includes("cannot be ruled out"), rows.join(" | ").slice(0, 200));
}

async function E(page) {
  page.allow4xx = ["/api/alerts/", "/api/sites/AGM-03/config", "/api/demo/scenario"];
  await login(page, "viewer");
  const list = await apiCall(page, "GET", "/api/alerts?status=open");
  const aid = list.body.items[0].id;
  const before = (await apiCall(page, "GET", "/api/alerts/" + aid)).body.alert;
  await go(page, "#/alerts/" + aid, ".stepper");
  check("E", "viewer sees no action buttons", await page.locator(".alert-controls").count() === 0 && (await page.locator(".callout").first().textContent()).includes("Only reviewer"));
  const ack = await apiCall(page, "POST", `/api/alerts/${aid}/acknowledge`, {});
  const act = await apiCall(page, "POST", `/api/alerts/${aid}/actions`, { action_type: "note", notes: "sneaky" });
  const cfg = await apiCall(page, "PUT", "/api/sites/AGM-03/config", { overrides: {} });
  const sim = await apiCall(page, "POST", "/api/demo/scenario", { site_ids: ["AGM-03"], preset: "normal" });
  check("E", "direct API mutations denied with 403", [ack, act, cfg, sim].every(r => r.status === 403), [ack, act, cfg, sim].map(r => r.status).join(","));
  const after = (await apiCall(page, "GET", "/api/alerts/" + aid)).body;
  check("E", "no mutation happened", after.alert.status === before.status && after.alert.updated_at === before.updated_at && !after.actions.some(a => a.notes === "sneaky"));
  await go(page, "#/settings", "textarea.code");
  check("E", "threshold editor disabled for viewer", await page.locator("textarea.code").isDisabled() && await page.locator("text=Save thresholds").isDisabled());
  await go(page, "#/simulator", ".preset-list");
  check("E", "simulator read-only for viewer", await page.locator("text=Apply scenario and re-assess").isDisabled());
}

async function UI(page) {
  await login(page, "admin");
  for (const [hash, sel] of [["#/", ".grid-overview"], ["#/map", ".map-svg"], ["#/sites", ".site-card"], ["#/alerts", ".page-head"],
    ["#/simulator", ".preset-list"], ["#/incidents", ".incident-detail h2"], ["#/sources", ".source"], ["#/evaluation", ".not-evaluated"],
    ["#/audit", "table.audit"], ["#/settings", "textarea.code"]]) {
    await go(page, hash, sel);
    check("UI", `route ${hash} renders`, true);
  }
  check("UI", "evaluation shows Not evaluated yet", (await page.goto(BASE + "/#/evaluation"), await page.waitForSelector(".not-evaluated"), await page.locator(".not-evaluated h2").textContent()) === "Not evaluated yet");
  await go(page, "#/incidents", ".incident-detail h2");
  await page.fill("input[name=q]", "gaurikund"); await page.click("text=Apply filters");
  await page.waitForTimeout(500);
  check("UI", "incident search filters", await page.locator(".incident-layout tbody tr").count() >= 1 && (await page.locator(".incident-layout tbody").textContent()).toLowerCase().includes("gaurikund"));
  await page.selectOption("select[name=origin]", "SYNTHETIC"); await page.fill("input[name=q]", ""); await page.click("text=Apply filters"); await page.waitForTimeout(500);
  const titles = await page.locator(".incident-layout tbody .linkish").allTextContents();
  check("UI", "synthetic filter only shows [SYNTHETIC] records", titles.length > 0 && titles.every(t => t.startsWith("[SYNTHETIC]")), titles.join("|"));
  const links = await page.locator(".incident-detail a[target=_blank]").evaluateAll(as => as.map(a => a.href));
  check("UI", "external links are http(s) only", links.every(h => /^https?:/.test(h)));
  await go(page, "#/settings", "textarea.code");
  await page.fill("textarea.code", '{"landslide":{"rain_24h_mm":{"watch":200,"high":100}}}');
  page.allow4xx = ["/config"];
  await page.click("text=Save thresholds");
  await page.waitForSelector(".form-error:not(:empty)");
  check("UI", "invalid thresholds rejected with message", (await page.locator(".form-error").first().textContent()).includes("watch"));
  await page.fill("textarea.code", "{not json");
  await page.click("text=Save thresholds");
  check("UI", "malformed JSON caught client-side", (await page.locator(".form-error").first().textContent()).includes("valid JSON"));
  page.allow4xx = ["/config", "/api/sites/NOPE"];
  await go(page, "#/nope", ".error-box");
  check("UI", "unknown route shows error state", true);
  await go(page, "#/sites/NOPE", ".error-box");
  check("UI", "unknown site shows error with retry", await page.locator(".error-box button").count() === 1);
  const a = await apiCall(page, "GET", "/api/assessments?limit=1");
  await go(page, `#/assessments/${a.body.items[0].id}`, ".assess");
  await page.click("text=Explain in plain language");
  await page.waitForSelector(".explain-text");
  check("UI", "template explanation fallback shown", (await page.locator(".explain").textContent()).includes("Template explanation"));
  // Mobile layout
  await page.setViewportSize({ width: 390, height: 844 });
  for (const hash of ["#/", "#/sites/SNP-05", "#/alerts", "#/simulator"]) {
    await go(page, hash, ".page-head");
    check("UI", `no horizontal overflow on mobile ${hash}`, await noHorizontalOverflow(page));
  }
  check("UI", "mobile menu button visible", await page.locator(".menu-btn").isVisible());
  await page.click(".menu-btn");
  check("UI", "mobile menu opens", await page.locator(".sidenav").isVisible());
  await shot(page, "UI-mobile");
}

// --------------------------------------------------------------- restart phase
async function F(page) {
  await login(page, "reviewer");
  const all = await apiCall(page, "GET", "/api/alerts?status=resolved");
  check("F", "resolved alert persisted across restart", all.body.total >= 1);
  const d = await apiCall(page, "GET", "/api/alerts/" + all.body.items[0].id);
  check("F", "actions persisted in order", d.body.actions.map(a => a.action_type).join(",") === "acknowledge,field_verification,resolve");
  const v = await apiCall(page, "GET", "/api/audit-log/verify");
  check("F", "audit chain valid after restart", v.body.valid === true, JSON.stringify(v.body));
  await go(page, "#/sites/SNP-05", ".sensor");
  const states = await page.locator(".sensor .state").allTextContents();
  check("F", "sensors report fresh data after restart (gateway resumed)", states.filter(s => s === "Reporting").length >= 2, states.join(","));
  await go(page, "#/sites/AGM-03", ".sensor");
  const ov = await apiCall(page, "GET", "/api/overview");
  check("F", "overview timestamps are current", Date.now() - new Date(ov.body.generated_at).getTime() < 120e3);
}

// ------------------------------------------------------------ production phase
async function G(page) {
  page.allow4xx = ["/api/demo/"];
  await login(page, "admin");
  const meta = await apiCall(page, "GET", "/api/meta");
  check("G", "production mode reported", meta.body.environment === "production" && meta.body.demo_endpoints === false);
  check("G", "simulator hidden from navigation", await page.locator(".sidenav a[data-nav=simulator]").count() === 0);
  const sim = await apiCall(page, "POST", "/api/demo/scenario", { site_ids: ["AGM-03"], preset: "normal" });
  const pre = await apiCall(page, "GET", "/api/demo/presets");
  check("G", "demo routes disabled (404)", sim.status === 404 && pre.status === 404, `${sim.status} ${pre.status}`);
  await page.click("text=Sign out");
  await page.waitForSelector(".login-card");
  check("G", "no demo-password hint on login page", (await page.locator(".login-card").textContent()).indexOf("Demo sign-in") === -1);
}

(async () => {
  const browser = await chromium.launch();
  const plan = { main: [["A: normal operation", A], ["B: increasing landslide risk", B], ["C: flash flood", C], ["D: sensor outage", D],
                        ["E: unauthorised actions", E], ["UI: pages, filters, errors, mobile", UI]],
                 restart: [["F: restart and persistence", F]], production: [["G: production safeguards", G]] }[phase];
  for (const [name, fn] of plan) await scenario(name, fn, browser);
  await browser.close();
  console.log(JSON.stringify(results));
})().catch(e => { console.error(e); process.exit(2); });
