// Small SVG chart primitives: time-series line chart and hourly bar chart.
import { h, s, timeOnly, fmtNum } from "./dom.js";

export interface Pt { t: string; v: number | null; q?: string; o?: string }
export interface Threshold { value: number; label: string; kind: "watch" | "high" }

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

export function lineChart(opts: { points: Pt[]; unit: string; label: string; thresholds?: Threshold[]; gapS: number;
  hours: number; zeroBased?: boolean; cumulativeNote?: string }): HTMLElement {
  const W = 640, H = 190, L = 46, R = 12, T = 12, B = 26;
  const end = Date.now();
  const start = end - opts.hours * 3600 * 1000;
  const good = opts.points.filter(p => p.v !== null && p.q !== "bad" && p.q !== "missing") as (Pt & { v: number })[];
  const values = good.map(p => p.v).concat((opts.thresholds || []).map(t => t.value));
  let lo = opts.zeroBased ? 0 : Math.min(...values);
  let hi = Math.max(...values);
  if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
  if (hi - lo < 1e-6) { hi += 0.5; lo -= opts.zeroBased ? 0 : 0.5; }
  const pad = (hi - lo) * 0.08;
  hi = opts.zeroBased ? niceMax(hi + pad) : hi + pad;
  lo = opts.zeroBased ? 0 : lo - pad;
  const x = (t: number) => L + ((t - start) / (end - start)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img",
    "aria-label": `${opts.label} over the last ${opts.hours} hours, in ${opts.unit}` });

  // grid + y labels
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4;
    svg.appendChild(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
    svg.appendChild(s("text", { x: L - 6, y: y(v) + 4, class: "axis", "text-anchor": "end" }, fmtNum(v)));
  }
  // x labels every N hours
  const stepH = opts.hours <= 6 ? 1 : opts.hours <= 24 ? 6 : 12;
  const firstTick = Math.ceil(start / (stepH * 3600e3)) * stepH * 3600e3;
  for (let t = firstTick; t <= end; t += stepH * 3600e3) {
    svg.appendChild(s("line", { x1: x(t), x2: x(t), y1: H - B, y2: H - B + 4, class: "tick" }));
    svg.appendChild(s("text", { x: x(t), y: H - 8, class: "axis", "text-anchor": "middle" }, timeOnly(new Date(t).toISOString())));
  }
  for (const th of opts.thresholds || []) {
    if (th.value < lo || th.value > hi) continue;
    svg.appendChild(s("line", { x1: L, x2: W - R, y1: y(th.value), y2: y(th.value), class: `thr thr-${th.kind}` }));
    svg.appendChild(s("text", { x: W - R - 2, y: y(th.value) - 4, class: `thr-label thr-${th.kind}`, "text-anchor": "end" }, th.label));
  }
  // One line per origin, with gaps where reporting stopped. Readings of different origins are
  // separate series and are never joined into one line (HDEWS-033).
  let prev: number | null = null;
  const origins = [...new Set(good.map(p => p.o || "UNKNOWN"))];
  for (const origin of origins) {
    let d = "";
    let last: number | null = null;
    for (const p of good.filter(q => (q.o || "UNKNOWN") === origin)) {
      const t = new Date(p.t).getTime();
      const cmd = last === null || t - last > opts.gapS * 1000 * 2.5 ? "M" : "L";
      d += `${cmd}${x(t).toFixed(1)},${y(p.v).toFixed(1)} `;
      last = t;
    }
    if (d) svg.appendChild(s("path", { d, class: origin === "SIMULATED" ? "series series-sim" : "series", "data-origin": origin }));
  }
  for (const p of good) prev = Math.max(prev ?? 0, new Date(p.t).getTime());
  if (!good.length) prev = null;
  for (const p of good.filter(p => p.o === "OBSERVED")) {
    svg.appendChild(s("circle", { cx: x(new Date(p.t).getTime()), cy: y(p.v), r: 3.5, class: "obs-dot" }));
  }
  // trailing gap: data stops before now
  if (prev !== null && end - prev > opts.gapS * 1000 * 3) {
    svg.appendChild(s("rect", { x: x(prev), y: T, width: Math.max(0, x(end) - x(prev)), height: H - T - B, class: "nodata" }));
    svg.appendChild(s("text", { x: (x(prev) + x(end)) / 2, y: T + 14, class: "nodata-label", "text-anchor": "middle" }, "no data"));
  }
  // hover readout
  const cursor = s("line", { y1: T, y2: H - B, class: "cursor", visibility: "hidden" });
  const readout = h("div", { class: "chart-readout", "aria-live": "polite" }, good.length ? "Hover to read values" : "No readings in this window");
  svg.appendChild(cursor);
  svg.addEventListener("mousemove", (e: MouseEvent) => {
    if (!good.length) return;
    const r = svg.getBoundingClientRect();
    const t = start + ((e.clientX - r.left) / r.width * W - L) / (W - L - R) * (end - start);
    let best = good[0];
    for (const p of good) if (Math.abs(new Date(p.t).getTime() - t) < Math.abs(new Date(best.t).getTime() - t)) best = p;
    const bx = x(new Date(best.t).getTime());
    cursor.setAttribute("x1", String(bx)); cursor.setAttribute("x2", String(bx)); cursor.setAttribute("visibility", "visible");
    readout.textContent = `${timeOnly(best.t)} IST — ${fmtNum(best.v, opts.unit)}${best.o ? ` (${best.o.toLowerCase()})` : ""}`;
  });
  svg.addEventListener("mouseleave", () => cursor.setAttribute("visibility", "hidden"));
  return h("figure", { class: "chart-wrap" },
    h("figcaption", null, h("strong", null, opts.label), h("span", { class: "muted" }, ` ${opts.unit}`),
      opts.cumulativeNote ? h("span", { class: "muted" }, ` — ${opts.cumulativeNote}`) : null),
    svg, readout);
}

export function hourlyBars(opts: { hours: string[]; values: number[]; unit: string; label: string; max?: number }): HTMLElement {
  const W = 240, H = 54, B = 12;
  const max = opts.max ?? niceMax(Math.max(1, ...opts.values));
  const bw = W / opts.hours.length;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "bars", role: "img",
    "aria-label": `${opts.label}: hourly rainfall, last 24 hours, total ${fmtNum(opts.values.reduce((a, b) => a + b, 0), opts.unit)}` });
  svg.appendChild(s("line", { x1: 0, x2: W, y1: H - B, y2: H - B, class: "grid" }));
  opts.values.forEach((v, i) => {
    const bh = (v / max) * (H - B - 2);
    const r = s("rect", { x: i * bw + 1, y: H - B - bh, width: bw - 2, height: Math.max(bh, v > 0 ? 1 : 0), class: v >= 15 ? "bar bar-hot" : "bar" });
    r.appendChild(s("title", {}, `${timeOnly(opts.hours[i])} IST: ${fmtNum(v, opts.unit)}`));
    svg.appendChild(r);
  });
  svg.appendChild(s("text", { x: 0, y: H - 1, class: "axis" }, "−24 h"));
  svg.appendChild(s("text", { x: W, y: H - 1, class: "axis", "text-anchor": "end" }, "now"));
  return svg as unknown as HTMLElement;
}
