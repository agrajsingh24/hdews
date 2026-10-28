// Self-contained Web-Mercator SVG map with pan/zoom, layer toggles and optional online OSM tiles.
import { h, s, clear, TIER_LABEL, HAZARD } from "./dom.js";

const TILE = 256;
const TIER_RANK: Record<string, number> = { INSUFFICIENT_DATA: 1.5, LOW: 0, ELEVATED: 2, HIGH: 3 };

function project(lon: number, lat: number, z: number): [number, number] {
  const size = TILE * Math.pow(2, z);
  const x = (lon + 180) / 360 * size;
  const sin = Math.sin(lat * Math.PI / 180);
  const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size;
  return [x, y];
}
function unproject(x: number, y: number, z: number): [number, number] {
  const size = TILE * Math.pow(2, z);
  const lon = x / size * 360 - 180;
  const n = Math.PI - 2 * Math.PI * y / size;
  return [lon, 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)))];
}

export function worstTier(assessments: Record<string, any>): { tier: string; reliability: string } {
  let tier = "NONE", rel = "GOOD", rank = -1;
  const relRank: Record<string, number> = { GOOD: 0, DEGRADED: 1, POOR: 2 };
  for (const a of Object.values(assessments || {})) {
    if (!a) continue;
    const r = TIER_RANK[a.risk_tier] ?? -1;
    if (r > rank) { rank = r; tier = a.risk_tier; }
    if ((relRank[a.reliability] ?? 0) > (relRank[rel] ?? 0)) rel = a.reliability;
  }
  return { tier, reliability: rel };
}

export interface MapOptions {
  data: any;
  layers: Record<string, boolean>;
  tiles: boolean;
  onSite?: (id: string) => void;
  selected?: string | null;
  height?: number;
  interactive?: boolean;
}

export function createMap(opts: MapOptions): { el: HTMLElement; render: () => void; setSelected: (id: string | null) => void; update: (o: Partial<MapOptions>) => void } {
  const bbox = opts.data.pilot_area.bbox as [number, number, number, number];
  let z = 10.2;
  const c0 = project((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, z);
  let cx = c0[0], cy = c0[1];
  const tileHost = h("div", { class: "map-tiles", "aria-hidden": "true" });
  const svg = s("svg", { class: "map-svg", role: "group", "aria-label": "Pilot area map" });
  const status = h("div", { class: "map-tilestatus" });
  const el = h("div", { class: "map", style: `height:${opts.height || 520}px` }, tileHost, svg, status);
  let dragging: { x: number; y: number; cx: number; cy: number } | null = null;
  let tileErrors = 0;

  const toScreen = (lon: number, lat: number, w: number, hgt: number): [number, number] => {
    const [x, y] = project(lon, lat, z);
    return [x - cx + w / 2, y - cy + hgt / 2];
  };

  function fitToBox(): void {
    const w = el.clientWidth || 600, hh = el.clientHeight || 500;
    for (let zz = 13; zz >= 6; zz -= 0.1) {
      const a = project(bbox[0], bbox[3], zz), b = project(bbox[2], bbox[1], zz);
      if (b[0] - a[0] < w * 0.92 && b[1] - a[1] < hh * 0.92) {
        z = zz; cx = (a[0] + b[0]) / 2; cy = (a[1] + b[1]) / 2; return;
      }
    }
  }

  function zoomBy(dz: number, sx?: number, sy?: number): void {
    const w = el.clientWidth, hh = el.clientHeight;
    const px = sx ?? w / 2, py = sy ?? hh / 2;
    const [lon, lat] = unproject(cx - w / 2 + px, cy - hh / 2 + py, z);
    z = Math.min(14, Math.max(7, z + dz));
    const [nx, ny] = project(lon, lat, z);
    cx = nx - (px - w / 2); cy = ny - (py - hh / 2);
    render();
  }

  function renderTiles(w: number, hh: number): void {
    clear(tileHost);
    status.textContent = "";
    if (!opts.tiles) return;
    const zi = Math.round(z);
    const scale = Math.pow(2, z - zi);
    const [ox, oy] = [cx / scale - w / 2 / scale, cy / scale - hh / 2 / scale];
    const x0 = Math.floor(ox / TILE), y0 = Math.floor(oy / TILE);
    const x1 = Math.floor((ox + w / scale) / TILE), y1 = Math.floor((oy + hh / scale) / TILE);
    for (let tx = x0; tx <= x1; tx++) for (let ty = y0; ty <= y1; ty++) {
      const img = h("img", { src: `https://tile.openstreetmap.org/${zi}/${tx}/${ty}.png`, alt: "", referrerpolicy: "strict-origin-when-cross-origin",
        draggable: "false", width: TILE * scale, height: TILE * scale,
        style: `left:${(tx * TILE - ox) * scale}px;top:${(ty * TILE - oy) * scale}px;width:${TILE * scale}px;height:${TILE * scale}px` });
      img.addEventListener("error", () => { img.remove(); tileErrors++; status.textContent = "Online basemap unavailable — showing vector layers only."; });
      tileHost.appendChild(img);
    }
    status.appendChild(h("span", null, "Basemap © ", h("a", { href: "https://www.openstreetmap.org/copyright", target: "_blank", rel: "noopener" }, "OpenStreetMap contributors")));
    if (tileErrors) status.appendChild(h("span", null, " (some tiles failed to load)"));
  }

  function render(): void {
    const w = el.clientWidth || 600, hh = el.clientHeight || 500;
    svg.setAttribute("viewBox", `0 0 ${w} ${hh}`);
    clear(svg);
    renderTiles(w, hh);
    const defs = s("defs");
    const pat = s("pattern", { id: "hatch", width: 5, height: 5, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
      s("rect", { width: 5, height: 5, class: "hatch-bg" }), s("line", { x1: 0, y1: 0, x2: 0, y2: 5, class: "hatch-line" }));
    defs.appendChild(pat);
    svg.appendChild(defs);

    // graticule (0.1°) when no tiles
    if (!opts.tiles) {
      const g = s("g", { class: "graticule" });
      for (let lon = 78.7; lon <= 79.4; lon += 0.1) {
        const [x] = toScreen(lon, 30, w, hh);
        g.appendChild(s("line", { x1: x, x2: x, y1: 0, y2: hh }));
      }
      for (let lat = 30.1; lat <= 30.9; lat += 0.1) {
        const [, y] = toScreen(79, lat, w, hh);
        g.appendChild(s("line", { x1: 0, x2: w, y1: y, y2: y }));
        g.appendChild(s("text", { x: 4, y: y - 3 }, `${lat.toFixed(1)}°N`));
      }
      svg.appendChild(g);
    }
    // pilot area box
    const [ax, ay] = toScreen(bbox[0], bbox[3], w, hh), [bx, by] = toScreen(bbox[2], bbox[1], w, hh);
    svg.appendChild(s("rect", { x: ax, y: ay, width: bx - ax, height: by - ay, class: "pilot-box" }));
    svg.appendChild(s("text", { x: ax + 6, y: ay + 16, class: "pilot-label" }, "Pilot study area (box, not district boundary)"));

    const L = opts.data.layers;
    if (opts.layers.hazard_zones) {
      const g = s("g", { class: "zones" });
      for (const zn of L.hazard_zones.items) {
        const site = L.sites.items.find((x: any) => x.id === zn.site_id);
        const { tier } = worstTier(site?.assessments);
        const [x, y] = toScreen(zn.center[0], zn.center[1], w, hh);
        const mpp = 156543.03 * Math.cos(zn.center[1] * Math.PI / 180) / Math.pow(2, z);
        const c = s("circle", { cx: x, cy: y, r: zn.radius_km * 1000 / mpp, class: `zone zone-${tier}` });
        c.appendChild(s("title", {}, `${zn.name} (simulated illustrative buffer)`));
        g.appendChild(c);
      }
      svg.appendChild(g);
    }
    if (opts.layers.rivers) {
      const g = s("g", { class: "rivers" });
      for (const r of L.rivers.items) {
        const pts = r.coordinates.map(([lon, lat]: number[]) => toScreen(lon, lat, w, hh).map(v => v.toFixed(1)).join(",")).join(" ");
        const pl = s("polyline", { points: pts, class: "river" });
        pl.appendChild(s("title", {}, r.name));
        g.appendChild(pl);
      }
      svg.appendChild(g);
    }
    if (opts.layers.places) {
      for (const p of L.places.items) {
        const [x, y] = toScreen(p.longitude, p.latitude, w, hh);
        svg.appendChild(s("circle", { cx: x, cy: y, r: 2.5, class: "place" }));
        svg.appendChild(s("text", { x: x + 6, y: y + 4, class: "place-label" }, p.name));
      }
    }
    if (opts.layers.incidents) {
      for (const inc of L.incidents.items) {
        const [x, y] = toScreen(inc.longitude, inc.latitude, w, hh);
        const d = s("path", { d: `M${x},${y - 6} L${x + 6},${y} L${x},${y + 6} L${x - 6},${y} Z`, class: `incident incident-${inc.origin}` });
        d.appendChild(s("title", {}, `${inc.title} — ${inc.event_date} (${inc.origin === "SYNTHETIC" ? "synthetic demo record" : "public report"})`));
        svg.appendChild(d);
      }
    }
    if (opts.layers.sites) {
      const placed: [number, number][] = [];
      for (const site of L.sites.items) {
        const [x, y] = toScreen(site.longitude, site.latitude, w, hh);
        const { tier, reliability } = worstTier(site.assessments);
        const alerting = opts.data.open_alerts.some((a: any) => a.site_id === site.id && a.status === "REVIEW_REQUIRED");
        const g = s("g", { class: `site${opts.selected === site.id ? " selected" : ""}`, tabindex: opts.onSite ? 0 : undefined,
          role: opts.onSite ? "button" : undefined,
          "aria-label": `${site.name}: ${TIER_LABEL[tier] || "not assessed"}, reliability ${reliability.toLowerCase()}${alerting ? ", alert awaiting review" : ""}` });
        if (alerting) g.appendChild(s("circle", { cx: x, cy: y, r: 17, class: "alert-ring" }));
        g.appendChild(s("circle", { cx: x, cy: y, r: 10, class: `site-dot tier-fill-${tier} rel-${reliability}`,
          fill: tier === "INSUFFICIENT_DATA" ? "url(#hatch)" : undefined }));
        g.appendChild(s("circle", { cx: x + 8, cy: y - 8, r: 3.5, class: "sim-dot" }));
        // Simple collision avoidance: flip the label to the left (and nudge down) if it would overlap one already placed.
        const clash = placed.some(([px, py]) => Math.abs(px - x) < 160 && Math.abs(py - y) < 16);
        const label = clash
          ? s("text", { x: x - 15, y: y + 12, class: "site-label", "text-anchor": "end" }, site.name)
          : s("text", { x: x + 15, y: y + 4, class: "site-label" }, site.name);
        placed.push([x, y]);
        g.appendChild(label);
        g.appendChild(s("title", {}, `${site.name}\n${site.hazards.map((hz: string) => `${HAZARD[hz]}: ${TIER_LABEL[site.assessments[hz]?.risk_tier] || "—"} (${site.assessments[hz]?.reliability?.toLowerCase() || "—"})`).join("\n")}\nSimulated telemetry`));
        if (opts.onSite) {
          g.addEventListener("click", (e) => { e.stopPropagation(); opts.onSite!(site.id); });
          g.addEventListener("keydown", (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); opts.onSite!(site.id); } });
        }
        svg.appendChild(g);
      }
    }
    // scale bar
    const mpp = 156543.03 * Math.cos(30.5 * Math.PI / 180) / Math.pow(2, z);
    const km = [1, 2, 5, 10, 20].find(k => k * 1000 / mpp > 70) || 20;
    const len = km * 1000 / mpp;
    svg.appendChild(s("line", { x1: 14, x2: 14 + len, y1: hh - 16, y2: hh - 16, class: "scalebar" }));
    svg.appendChild(s("text", { x: 14, y: hh - 22, class: "scale-label" }, `${km} km`));
  }

  if (opts.interactive !== false) {
    svg.addEventListener("pointerdown", (e: PointerEvent) => {
      if ((e.target as Element).closest(".site")) return;
      dragging = { x: e.clientX, y: e.clientY, cx, cy };
      svg.setPointerCapture(e.pointerId);
    });
    svg.addEventListener("pointermove", (e: PointerEvent) => {
      if (!dragging) return;
      cx = dragging.cx - (e.clientX - dragging.x); cy = dragging.cy - (e.clientY - dragging.y);
      render();
    });
    svg.addEventListener("pointerup", () => { dragging = null; });
    svg.addEventListener("wheel", (e: WheelEvent) => {
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      zoomBy(e.deltaY < 0 ? 0.5 : -0.5, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    el.appendChild(h("div", { class: "map-zoom" },
      h("button", { class: "btn btn-icon", type: "button", "aria-label": "Zoom in", onclick: () => zoomBy(1) }, "+"),
      h("button", { class: "btn btn-icon", type: "button", "aria-label": "Zoom out", onclick: () => zoomBy(-1) }, "−"),
      h("button", { class: "btn btn-icon", type: "button", "aria-label": "Reset view", title: "Reset view", onclick: () => { fitToBox(); render(); } }, "⤢")));
  }

  const ro = new ResizeObserver(() => render());
  requestAnimationFrame(() => { fitToBox(); render(); ro.observe(el); });

  return {
    el, render,
    setSelected(id) { opts.selected = id; render(); },
    update(o) { Object.assign(opts, o); render(); },
  };
}
