// Tryb „Zasoby” — port radius.py (launch_interactive_visualizer, radius.py:183-435) na canvas 2D.
// Dane i kontur liczy backend (lunar_resources.*); strona rysuje mapę, pasek kolorów i wykresy.
import { ApiError } from '/js/core/api-client.js';
import { makeSlider } from '../ui/slider.js';
import { chartRects, drawBarChart, fmtTick, niceTicks } from './resource-charts.js';

const FONT = '"DejaVu Sans", Arial, sans-serif';
const PT = 100 / 72;
const RETRY_MS = 5000; // Retry-After: 5 z backendu (ApiClient nie wystawia nagłówków)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Float jak repr() w Pythonie (csv.DictWriter zapisuje floaty przez repr). */
export function pyFloat(v) {
  if (!Number.isFinite(v)) return Number.isNaN(v) ? 'nan' : (v > 0 ? 'inf' : '-inf');
  if (v === 0) return Object.is(v, -0) ? '-0.0' : '0.0';
  const e = Math.floor(Math.log10(Math.abs(v)));
  if (e < -4 || e >= 16) {
    let [m, ex] = v.toExponential().split('e');
    const sign = ex[0] === '-' ? '-' : '+';
    ex = ex.replace(/^[+-]/, '').padStart(2, '0');
    return `${m}e${sign}${ex}`;
  }
  const s = String(v);
  return s.includes('.') || s.includes('e') ? s : `${s}.0`;
}

/** Tekst CSV jak export_rows_to_csv (radius.py:170-180): nagłówek z kluczy rows[0], przecinek, BOM, CRLF. */
export function rowsToCsv(rows) {
  if (!rows.length) return '';
  const cols = Object.keys(rows[0]);
  const cell = (v) => {
    const s = typeof v === 'number' ? pyFloat(v) : String(v ?? '');
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [cols.map(cell).join(',')];
  for (const r of rows) lines.push(cols.map((c) => cell(r[c])).join(','));
  return `﻿${lines.join('\r\n')}\r\n`;
}

const signed = (v, d) => { const s = v.toFixed(d); return s.startsWith('-') ? s : `+${s}`; };
const snap = (v, step) => { const r = Math.round(v / step) * step; return r === 0 ? 0 : r; };

export async function createResourcesMode({ root, api, endpoint }) {
  root.classList.add('res-root');
  root.innerHTML = `
    <div class="res-left">
      <canvas class="res-map"></canvas>
      <div class="res-controls">
        <fieldset class="res-radio"><legend>Map Overlay</legend></fieldset>
        <div class="res-main">
          <div class="res-sliders"></div>
          <div class="res-buttons">
            <button type="button" class="res-csv">Export CSV</button>
            <button type="button" class="res-reset">Reset (Imbrium)</button>
          </div>
          <div class="res-status"></div>
        </div>
      </div>
    </div>
    <div class="res-right"><canvas class="res-charts"></canvas></div>
    <div class="res-loading" hidden>Przygotowywanie map zasobów (NASA PDS)…</div>`;
  const $ = (sel) => root.querySelector(sel);
  const mapCv = $('.res-map');
  const chartCv = $('.res-charts');
  const overlay = $('.res-loading');
  const statusEl = $('.res-status');

  let alive = true;
  let active = false;
  const setLoading = (on) => { overlay.hidden = !on; };

  // --- katalog (static); przy 503 pokazuje nakładkę i ponawia ---
  async function retrying(fn, signal) {
    for (;;) {
      try {
        const out = await fn();
        setLoading(false);
        return out;
      } catch (err) {
        if (signal?.aborted || err?.name === 'AbortError') throw err;
        if (!(err instanceof ApiError) || err.status !== 503) throw err;
        setLoading(true);
        await sleep(RETRY_MS);
        if (signal?.aborted) throw new DOMException('aborted', 'AbortError');
      }
    }
  }
  const catalog = await retrying(() => api.getJson(endpoint('lunar_resources.catalog'), {}, { cache: true }));
  const layers = new Map(catalog.layers.map((l) => [l.key, l]));
  const keys = catalog.layers.map((l) => l.key);
  let layerKey = keys[0];
  const sl = catalog.sliders;
  const d = catalog.defaults;

  // --- suwaki i przyciski (radius.py:256-258, 270-289) ---
  const slidersEl = $('.res-sliders');
  const mk = (label, cfg, fmt, cls) => {
    const s = makeSlider(slidersEl, { label, min: cfg.min, max: cfg.max, value: cfg.init, format: fmt });
    s.el.classList.add(cls);
    s.onInput = (v) => { s.set(snap(v, cfg.step)); schedule(); };
    return s;
  };
  const sLat = mk('Latitude φ [°]', sl.lat_deg, (v) => v.toFixed(1), 'res-lat');
  const sLon = mk('Longitude λ [°]', sl.lon_deg, (v) => v.toFixed(1), 'res-lon');
  const sRad = mk('Radius R [km]', sl.radius_km, (v) => v.toFixed(1), 'res-rad');
  sLat.set(d.lat_deg); sLon.set(d.lon_deg); sRad.set(d.radius_km);

  const radioEl = $('.res-radio');
  for (const key of keys) {
    const lab = document.createElement('label');
    lab.innerHTML = `<input type="radio" name="res-layer" value="${key}"${key === layerKey ? ' checked' : ''}> <span></span>`;
    lab.querySelector('span').textContent = key;
    radioEl.append(lab);
  }
  radioEl.addEventListener('change', (e) => {
    if (e.target.name !== 'res-layer') return;
    layerKey = e.target.value;
    draw();
  });

  // --- obrazy warstw (cache per klucz); przy błędzie (503 przy starcie) ponowienie ---
  const images = new Map();
  function layerImage(key) {
    let entry = images.get(key);
    if (!entry) {
      entry = { img: new Image(), ready: false };
      entry.img.onload = () => { entry.ready = true; if (key === layerKey) draw(); };
      entry.img.onerror = () => {
        images.delete(key);
        if (alive) setTimeout(() => { if (key === layerKey) layerImage(key); }, RETRY_MS);
      };
      entry.img.src = layers.get(key).image_url;
      images.set(key, entry);
    }
    return entry;
  }

  // --- ROI: debounce 150 ms + AbortController + licznik generacji ---
  let view = null; // {lat, lon, rad, cap, rows, contour}
  let timer = null;
  let ctrl = null;
  let gen = 0;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(update, 150);
  }
  async function update() {
    ctrl?.abort();
    const mine = ++gen;
    const c = new AbortController();
    ctrl = c;
    const lat = sLat.value; const lon = sLon.value; const rad = sRad.value;
    try {
      const res = await retrying(
        () => api.getJson(endpoint('lunar_resources.roi'), { lat_deg: lat, lon_deg: lon, radius_km: rad }, { signal: c.signal }),
        c.signal,
      );
      if (mine !== gen) return;
      view = { lat, lon, rad, cap: res.roi.cap_area_km2, rows: res.rows, contour: res.contour_lonlat };
      draw();
    } catch (err) {
      if (err?.name === 'AbortError' || mine !== gen) return;
      console.error(err);
      statusEl.textContent = `Błąd: ${err?.message ?? err}`;
      statusEl.classList.add('res-error');
    }
  }

  // --- rysowanie ---
  function fit(cv) {
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth; const h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    }
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
  }
  const scaleOf = (w) => Math.max(0.6, Math.min(1.25, w / 850));

  function drawMap() {
    const { ctx, w: W, h: H } = fit(mapCv);
    ctx.fillStyle = '#12151a';
    ctx.fillRect(0, 0, W, H);
    if (!W || !H) return;
    const sc = scaleOf(W);
    const k = PT * sc;
    const font = (pt, bold = false) => `${bold ? 'bold ' : ''}${(pt * k).toFixed(1)}px ${FONT}`;
    const L = 52 * sc; const R = 10 * sc;
    const top = 34 * sc;
    const cbH = 14 * sc;
    const cbBottomSpace = 44 * sc; // podziałki + podpis paska
    const mapBottomSpace = 46 * sc; // podziałki + podpis osi X + odstęp do paska
    const mx = L; const my = top; const mw = W - L - R;
    const mh = H - top - mapBottomSpace - cbH - cbBottomSpace;
    const lon2x = (lon) => mx + ((lon + 180) / 360) * mw;
    const lat2y = (lat) => my + ((90 - lat) / 180) * mh;
    const layer = layers.get(layerKey);
    const entry = layerImage(layerKey);

    ctx.fillStyle = '#181c23';
    ctx.fillRect(mx, my, mw, mh);
    if (entry.ready) ctx.drawImage(entry.img, mx, my, mw, mh);

    // siatka co 30° (radius.py:243-245)
    ctx.save();
    ctx.beginPath(); ctx.rect(mx, my, mw, mh); ctx.clip();
    ctx.strokeStyle = 'rgba(255,255,255,0.35)';
    ctx.lineWidth = 0.5 * PT;
    ctx.setLineDash([1 * PT, 1.65 * PT]);
    ctx.beginPath();
    for (let lon = -180; lon <= 180; lon += 30) { ctx.moveTo(lon2x(lon), my); ctx.lineTo(lon2x(lon), my + mh); }
    for (let lat = -90; lat <= 90; lat += 30) { ctx.moveTo(mx, lat2y(lat)); ctx.lineTo(mx + mw, lat2y(lat)); }
    ctx.stroke();
    ctx.setLineDash([]);

    if (view) {
      // kontur R (radius.py:307-316): #00f5d4, 1.8 px
      ctx.strokeStyle = '#00f5d4';
      ctx.lineWidth = 1.8;
      ctx.lineJoin = 'round';
      for (const line of view.contour) {
        ctx.beginPath();
        line.forEach(([lo, la], i) => (i ? ctx.lineTo(lon2x(lo), lat2y(la)) : ctx.moveTo(lon2x(lo), lat2y(la))));
        ctx.stroke();
      }
      // znacznik „+” (radius.py:252): rozmiar 11 pt, grubość 2
      const cx = lon2x(view.lon); const cy = lat2y(view.lat);
      const arm = 11 * PT * sc / 2;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx - arm, cy); ctx.lineTo(cx + arm, cy);
      ctx.moveTo(cx, cy - arm); ctx.lineTo(cx, cy + arm);
      ctx.stroke();
    }
    ctx.restore();

    // ramka, podziałki, podpisy
    ctx.strokeStyle = '#d0d7de';
    ctx.lineWidth = 0.8 * PT;
    ctx.strokeRect(mx, my, mw, mh);
    ctx.fillStyle = '#d0d7de';
    ctx.font = font(8);
    ctx.beginPath();
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let lon = -180; lon <= 180; lon += 30) {
      ctx.moveTo(lon2x(lon), my + mh); ctx.lineTo(lon2x(lon), my + mh + 3.5 * k);
      ctx.fillText(String(lon), lon2x(lon), my + mh + 3.5 * k + 2 * sc);
    }
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (let lat = -90; lat <= 90; lat += 30) {
      ctx.moveTo(mx, lat2y(lat)); ctx.lineTo(mx - 3.5 * k, lat2y(lat));
      ctx.fillText(String(lat), mx - 3.5 * k - 3 * sc, lat2y(lat));
    }
    ctx.stroke();
    ctx.fillStyle = '#c9d1d9';
    ctx.font = font(8.5);
    ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
    ctx.fillText('Selenographic Longitude λ [°]  (click map to relocate target)', mx + mw / 2, my + mh + 30 * sc);
    ctx.save();
    ctx.translate(14 * sc, my + mh / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Selenographic Latitude φ [°]', 0, 0);
    ctx.restore();

    // tytuł (radius.py:318-326)
    if (view) {
      ctx.fillStyle = '#ffffff';
      ctx.font = font(10.2, true);
      const cap = Math.round(view.cap).toLocaleString('en-US');
      ctx.fillText(
        `Target: φ = ${signed(view.lat, 1)}°, λ = ${signed(view.lon, 1)}° | Radius R = ${view.rad.toFixed(0)} km (Spherical Cap Area: ${cap} km²)`,
        mx + mw / 2, my - 8 * sc,
      );
    }

    // pasek kolorów (radius.py:234-238) z colormap_u8
    const cy0 = my + mh + mapBottomSpace;
    const cm = layer.colormap_u8;
    const n = cm.length;
    for (let i = 0; i < n; i++) {
      const [r, g, b] = cm[i];
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      const x0 = mx + (i / n) * mw;
      ctx.fillRect(x0, cy0, mw / n + 0.6, cbH);
    }
    ctx.strokeStyle = '#444c56';
    ctx.lineWidth = 0.8 * PT;
    ctx.strokeRect(mx, cy0, mw, cbH);
    const ticks = niceTicks(layer.vmin, layer.vmax, 7);
    ctx.fillStyle = '#d0d7de';
    ctx.font = font(7.5);
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.strokeStyle = '#d0d7de';
    ctx.beginPath();
    for (const t of ticks) {
      const x = mx + ((t - layer.vmin) / (layer.vmax - layer.vmin)) * mw;
      ctx.moveTo(x, cy0 + cbH); ctx.lineTo(x, cy0 + cbH + 3.5 * k);
      ctx.fillText(fmtTick(t), x, cy0 + cbH + 3.5 * k + 2 * sc);
    }
    ctx.stroke();
    ctx.fillStyle = '#e6edf3';
    ctx.font = font(8);
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(`Active Layer: ${layer.title} [${layer.unit}]`, mx + mw / 2, cy0 + cbH + 36 * sc);
  }

  function drawCharts() {
    const { ctx, w: W, h: H } = fit(chartCv);
    ctx.fillStyle = '#12151a';
    ctx.fillRect(0, 0, W, H);
    if (!view || !W || !H) return;
    const sc = scaleOf(W * 1.5);
    const rects = chartRects(W, H);
    catalog.chart_groups.slice(0, 2).forEach((g, i) => {
      drawBarChart(ctx, g, view.rows, { rect: rects[i], radiusKm: view.rad, legend: i === 0, scale: sc });
    });
  }

  function draw() {
    if (!active) return;
    drawMap();
    drawCharts();
  }

  // --- sterowanie ---
  mapCv.addEventListener('click', (e) => {
    const rect = mapCv.getBoundingClientRect();
    const W = rect.width;
    const sc = scaleOf(W);
    const L = 52 * sc; const R = 10 * sc; const top = 34 * sc;
    const mh = rect.height - top - 46 * sc - 14 * sc - 44 * sc;
    const mw = W - L - R;
    const x = e.clientX - rect.left - L;
    const y = e.clientY - rect.top - top;
    if (x < 0 || y < 0 || x > mw || y > mh) return; // radius.py:394 (event.inaxes)
    const lon = Math.max(-180, Math.min(180, -180 + (x / mw) * 360));
    const lat = Math.max(-90, Math.min(90, 90 - (y / mh) * 180));
    sLat.set(snap(lat, 0.5)); // radius.py:399-402
    sLon.set(snap(lon, 0.5));
    schedule();
  });
  $('.res-reset').addEventListener('click', () => {
    sLat.set(20); sLon.set(-25); sRad.set(250); // radius.py:420-425
    schedule();
  });
  $('.res-csv').addEventListener('click', () => {
    if (!view) return;
    const name = `lunar_roi_lat${signed(sLat.value, 1)}_lon${signed(sLon.value, 1)}_R${sRad.value.toFixed(0)}km.csv`;
    const url = URL.createObjectURL(new Blob([rowsToCsv(view.rows)], { type: 'text/csv;charset=utf-8' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    statusEl.classList.remove('res-error');
    statusEl.textContent = `Exported CSV: ${name}`;
  });

  const ro = new ResizeObserver(() => draw());
  ro.observe(mapCv);
  ro.observe(chartCv);

  return {
    activate() {
      active = true;
      draw();
      update();
    },
    deactivate() {
      active = false;
      clearTimeout(timer);
      ctrl?.abort();
      gen++;
    },
    // do weryfikacji w konsoli
    _state: () => ({ view, layerKey, rowsToCsv }),
  };
}
