// Tryb „Orbita” — port neworb.main() (neworb.py:1101-1557). Fizyka liczy backend
// (lunar_orbit.initial / lunar_orbit.propagate, paczkami); przeglądarka odtwarza stan (TrackPlayer)
// i rysuje wszystko tak jak pygame: Księżyc shaderem per piksel, reszta na canvas 2D tymi samymi
// prostokątami, kolorami, czcionkami i testami trafień.
import { drawChart } from './charts.js';
import {
  FONT, FONT_BOLD, FONT_SMALL, circle, drawEarthMarker, drawSunMarker, fmtComma, fmtSigned, fmtWidth, line, rgb,
  roundRect, text, textSize, wrapLines,
} from './draw2d.js';
import { GroundTrackMap } from './ground-map.js';
import { createMoonRenderer } from './moon-render.js';
import { OrbitCamera, R_MOON, drawRuns, latlonToXyz, xyzToLatlon } from './orbit-camera.js';
import { TrackPlayer } from './track-player.js';

const DEG = Math.PI / 180;
const MAX_HISTORY = 240;

const norm = (v) => Math.hypot(v[0], v[1], v[2]);
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const fmtUtc = (ms) => new Date(ms).toISOString().slice(0, 19).replace('T', ' ');
const inside = (r, x, y) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;
const inflate = (r, dx, dy) => ({ x: r.x - dx / 2, y: r.y - dy / 2, w: r.w + dx, h: r.h + dy });

/** Siatka współrzędnych jak grid_lines() (neworb.py:819-830): punkty co 3°, na R × 1.004. */
function gridLines() {
  const lines = [];
  const R = R_MOON * 1.004;
  for (let lat = -75; lat <= 75; lat += 15) {
    const pts = [];
    for (let lon = -180; lon <= 180; lon += 3) pts.push(...latlonToXyz(lat, lon, R));
    lines.push(pts);
  }
  for (let lon = -180; lon < 180; lon += 15) {
    const pts = [];
    for (let lat = -90; lat <= 90; lat += 3) pts.push(...latlonToXyz(lat, lon, R));
    lines.push(pts);
  }
  return lines;
}

/** Okręgi rdzeni masconów jak _build_mascon_rings (neworb.py:797-816). */
function masconRings(mascons) {
  return mascons.map((m) => {
    const cu = latlonToXyz(m.lat_deg, m.lon_deg, 1.0);
    const ref = Math.abs(cu[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
    let e1 = [ref[1] * cu[2] - ref[2] * cu[1], ref[2] * cu[0] - ref[0] * cu[2], ref[0] * cu[1] - ref[1] * cu[0]];
    const n1 = norm(e1);
    e1 = e1.map((x) => x / n1);
    const e2 = [cu[1] * e1[2] - cu[2] * e1[1], cu[2] * e1[0] - cu[0] * e1[2], cu[0] * e1[1] - cu[1] * e1[0]];
    const psi = m.core_radius_km / R_MOON;
    const pts = [];
    for (let i = 0; i < 49; i++) {
      const a = (2 * Math.PI * i) / 48;
      for (let k = 0; k < 3; k++) {
        pts.push((Math.cos(psi) * cu[k] + Math.sin(psi) * (Math.cos(a) * e1[k] + Math.sin(a) * e2[k])) * R_MOON * 1.006);
      }
    }
    return { name: m.name, center: cu.map((x) => x * R_MOON * 1.012), pts };
  });
}

export async function createOrbitMode({ root, api, endpoint, clock }) {
  root.innerHTML = '';
  root.classList.add('orbit-root');
  const moon = createMoonRenderer(root);
  const overlay = document.createElement('canvas');
  overlay.className = 'orbit-overlay';
  overlay.tabIndex = 0;
  root.append(overlay);
  const ctx = overlay.getContext('2d');

  const catalog = await api.getJson(endpoint('lunar_orbit.catalog'), {}, { cache: true });
  const GM = catalog.gm_moon_km3_s2;
  const OMEGA = catalog.omega_moon_rad_s;
  const R_ESCAPE = catalog.r_escape_km;
  const presets = catalog.presets.map((p) => [p.label, p.id]);
  const GRID = gridLines();
  const RINGS = masconRings(catalog.mascons);
  const LANDMARK_XYZ = catalog.landmarks.flatMap((lm) => latlonToXyz(lm.lat_deg, lm.lon_deg, R_MOON * 1.012));
  const circularSpeed = (alt) => Math.sqrt(GM / (R_MOON + alt));
  const inertialVelocity = (p, v) => [v[0] - OMEGA * p[1], v[1] + OMEGA * p[0], v[2]];

  // --- stan (neworb.py:1135-1158) ---
  let currentPreset = 'LRO';
  let customDialog = false;
  const customFields = ['100', '45', circularSpeed(100.0).toFixed(4)];
  let customActive = 0;
  let customError = '';
  let historyAlt = [];
  let historyVel = [];
  let timeElapsed = 0.0;
  let crashed = false;
  let crashReason = '';
  let paused = false;
  let perturbations = true;
  let useMascons = true;
  let showMascons = true;
  let showGroundTrack = true;
  let fitPending = true;
  const camera = new OrbitCamera(15.0, 0.0, 6000.0);
  let draggingCam = false;
  let lastMouse = [0, 0];
  const slider = { x: 30, y: 845, w: 300, h: 10, min: 1.0, max: 100000.0, val: 30.0, label: 'Sim speed', dragging: false };
  let epochMs = clock.t;
  let netError = '';

  const player = new TrackPlayer();
  let trackMap = null;
  moon.ready.then((levels) => { trackMap = new GroundTrackMap(levels); }).catch((e) => { netError = String(e?.message ?? e); });

  // --- backend ---
  let inflight = null;
  let generation = 0;

  async function fetchInitial(preset, custom) {
    const params = { t: new Date(epochMs).toISOString(), preset };
    if (custom) Object.assign(params, { altitude_km: custom[0], inclination_deg: custom[1], speed_kms: custom[2] });
    return api.getJson(endpoint('lunar_orbit.initial'), params);
  }

  /** replaceAfter: przy zmianie fizyki (M/P) stare próbki po tym czasie są podmieniane dopiero po
   *  nadejściu nowej paczki — sonda nie cofa się do ostatniej próbki w oczekiwaniu na backend. */
  function requestChunk(from, replaceAfter = null) {
    inflight?.abort();
    const ctrl = new AbortController();
    inflight = ctrl;
    const gen = generation;
    const duration = Math.min(345600, Math.max(600, slider.val * 8));
    const sampleDt = Math.max(10, duration / 1500);
    const [x, y, z] = from.pos;
    const [vx, vy, vz] = from.vel;
    api.getJson(endpoint('lunar_orbit.propagate'), {
      t: new Date(epochMs + from.t * 1000).toISOString(),
      x_km: x, y_km: y, z_km: z, vx_kms: vx, vy_kms: vy, vz_kms: vz,
      duration_s: duration, sample_dt_s: sampleDt,
      use_mascons: useMascons, third_body: perturbations,
    }, { signal: ctrl.signal }).then((tr) => {
      if (gen !== generation || ctrl.signal.aborted) return;
      if (replaceAfter !== null) player.truncateAfter(replaceAfter);
      player.append(tr, from.t);
      netError = '';
    }).catch((err) => {
      if (err?.name !== 'AbortError') netError = `Backend error: ${err?.message ?? err}`;
    }).finally(() => { if (inflight === ctrl) inflight = null; });
  }

  /** set_state + reset czasu do epoki (neworb.py:1166-1189). */
  async function setStateFrom(promise) {
    generation += 1;
    const gen = generation;
    inflight?.abort();
    inflight = null;
    try {
      const st = await promise;
      if (gen !== generation) return;
      player.reset(st);
      historyAlt = [];
      historyVel = [];
      timeElapsed = 0.0;
      crashed = false;
      crashReason = '';
      fitPending = true;
      syncClock();
      requestChunk({ t: 0, pos: st.pos_km, vel: st.vel_kms });
    } catch (err) {
      netError = `Backend error: ${err?.message ?? err}`;
    }
  }
  // Parametry ostatniej własnej orbity: reset do nowej epoki (zmiana czasu w nagłówku) zachowuje
  // orbitę użytkownika zamiast podmieniać ją na domyślne 100 km / 45°.
  let lastCustom = null;
  const resetSim = (preset) => {
    if (preset && preset !== 'RESET') currentPreset = preset;
    return setStateFrom(currentPreset === 'Custom'
      ? fetchInitial('CUSTOM', lastCustom ?? undefined)
      : fetchInitial(currentPreset));
  };
  const applyCustom = (alt, inc, speed) => {
    lastCustom = [alt, inc, speed];
    currentPreset = 'Custom';
    customDialog = false;
    return setStateFrom(fetchInitial('CUSTOM', [alt, inc, speed]));
  };

  /** M / P w trakcie lotu: dalsza propagacja z dokładnego stanu ostatniej próbki ≤ teraz. */
  function physicsChanged() {
    if (crashed) return;
    const s = player.lastSampleAtOrBefore(timeElapsed);
    if (!s) return;
    generation += 1;
    requestChunk(s, s.t);
  }

  // --- wspólny zegar strony: czas = epoka + time_elapsed; Play/Pauza = !paused ---
  let selfClock = false;
  function syncClock() {
    selfClock = true;
    clock.seek(epochMs + timeElapsed * 1000);
    if (paused === clock.playing) { if (paused) clock.pause(); else clock.play(); }
    selfClock = false;
  }
  const onTime = (ev) => {
    if (selfClock || ev.detail?.reason !== 'seek') return;
    epochMs = clock.t;   // nowa epoka jak --epoch → reset presetu
    resetSim();
  };
  const onPlay = () => { if (!selfClock) paused = !clock.playing; };

  // --- wejście (neworb.py:1205-1293) ---
  const layout = { width: 1, height: 1, panelX: 650, panelW: 250, panelTop: 75, panelH: 300 };
  const presetRect = (i) => ({ x: 25 + i * 137, y: 20, w: 128, h: 34 });
  const sliderRect = () => ({ x: slider.x, y: slider.y, w: slider.w, h: slider.h });
  // Okno „Custom orbit”: jedna geometria dla rysowania i trafień, wyśrodkowana na kanwie;
  // wysokość rośnie z liczbą wierszy podpowiedzi / błędu, żeby tekst nie wychodził poza ramkę.
  const DLG_W = 360;
  const DLG_PAD = 24;
  const DLG_HINT = 'Tab: next field  Enter: apply  Esc: cancel';
  const HELP = 'Drag: rotate  Scroll: zoom  Space: pause  E: Earth view  '
    + 'G: ground track  P: Earth + Sun  M: mascon gravity  V: mascon map';
  function dialogLayout() {
    const innerW = DLG_W - 2 * DLG_PAD;
    const msgFont = customError ? FONT : FONT_SMALL;
    const msgRows = customError
      ? wrapLines(ctx, customError, innerW, FONT)
      : wrapLines(ctx, DLG_HINT, innerW, FONT_SMALL, '  ');
    const msgLineH = customError ? 19 : 17;
    const msgY = 354;
    const h = msgY + msgRows.length * msgLineH + 16;
    const x = Math.round((layout.width - DLG_W) / 2);
    const y = Math.max(12, Math.round((layout.height - h) / 2));
    const btnW = Math.trunc((innerW - 10) / 2);
    return {
      box: { x, y, w: DLG_W, h },
      inner: { x: x + DLG_PAD, w: innerW },
      titleY: y + 22,
      fields: [0, 1, 2].map((fi) => ({ x: x + DLG_PAD, y: y + 82 + fi * 70, w: innerW, h: 38 })),
      suggestY: y + 276,
      apply: { x: x + DLG_PAD, y: y + 302, w: btnW, h: 40 },
      cancel: { x: x + DLG_W - DLG_PAD - btnW, y: y + 302, w: btnW, h: 40 },
      msg: { rows: msgRows, font: msgFont, lineH: msgLineH, y: y + msgY },
    };
  }
  const sliderUpdate = (mx) => {
    const ratio = Math.max(0, Math.min(1, (mx - slider.x) / Math.max(1, slider.w)));
    slider.val = slider.min * (slider.max / slider.min) ** ratio;
  };

  function pyFloat(s) {
    const t = s.trim();
    if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(t)) throw new Error(`Not a number: '${s}'`);
    return Number(t);
  }

  function onMouseDown(ev) {
    const r = overlay.getBoundingClientRect();
    const mx = ev.clientX - r.left;
    const my = ev.clientY - r.top;
    if (ev.button !== 0) return;
    if (customDialog) {
      const dl = dialogLayout();
      for (let fi = 0; fi < 3; fi++) if (inside(dl.fields[fi], mx, my)) customActive = fi;
      if (inside(dl.apply, mx, my)) {
        try {
          const [alt, inc, speed] = customFields.map(pyFloat);
          if (!(alt >= 1.0 && alt <= 100000.0)) throw new Error('Altitude must be 1–100000 km.');
          if (!(inc >= 0.0 && inc <= 180.0)) throw new Error('Inclination must be 0–180°.');
          if (!(speed > 0.0 && speed <= 10.0)) throw new Error('Speed must be 0–10 km/s.');
          applyCustom(alt, inc, speed);
        } catch (exc) {
          customError = exc.message || 'Enter valid numbers.';
        }
      } else if (inside(dl.cancel, mx, my)) {
        customDialog = false;
      }
      return;
    }
    if (inside(inflate(sliderRect(), 12, 14), mx, my)) {
      slider.dragging = true;
      sliderUpdate(mx);
      overlay.setPointerCapture(ev.pointerId);
      return;
    }
    for (let i = 0; i < presets.length; i++) {
      if (inside(presetRect(i), mx, my)) {
        const key = presets[i][1];
        if (key === 'CUSTOM') { customDialog = true; customError = ''; } else resetSim(key);
        return;
      }
    }
    if (mx < layout.panelX && my > 65) {
      draggingCam = true;
      lastMouse = [ev.clientX, ev.clientY];
      overlay.setPointerCapture(ev.pointerId);
    }
  }
  function onMouseUp(ev) {
    if (ev.button !== 0) return;
    draggingCam = false;
    slider.dragging = false;
  }
  function onMouseMove(ev) {
    const r = overlay.getBoundingClientRect();
    if (slider.dragging) { sliderUpdate(ev.clientX - r.left); return; }
    if (!draggingCam) return;
    const dx = ev.clientX - lastMouse[0];
    const dy = ev.clientY - lastMouse[1];
    lastMouse = [ev.clientX, ev.clientY];
    const dpp = 0.25 * Math.min(1.0, Math.max(0.08, (camera.dist - R_MOON) / 4000.0));
    camera.setView(camera.lat + dy * dpp, camera.lon - dx * dpp);
  }
  function onWheel(ev) {
    ev.preventDefault();
    if (customDialog || !ev.deltaY) return;
    camera.zoom(ev.deltaY < 0 ? 0.9 : 1.1);
  }
  function onKey(ev) {
    if (ev.target instanceof HTMLInputElement || ev.target instanceof HTMLSelectElement) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const k = ev.key;
    if (customDialog) {
      if (k === 'Escape') customDialog = false;
      else if (k === 'Tab') customActive = (customActive + (ev.shiftKey ? 2 : 1)) % 3;
      else if (k === 'Enter') {
        try {
          const [alt, inc, speed] = customFields.map(pyFloat);
          if (!(alt >= 1.0 && alt <= 100000.0 && inc >= 0.0 && inc <= 180.0 && speed > 0.0 && speed <= 10.0)) {
            throw new Error('Out of range.');
          }
          applyCustom(alt, inc, speed);
        } catch {
          customError = 'Invalid input or value out of range.';
        }
      } else if (k === 'Backspace') customFields[customActive] = customFields[customActive].slice(0, -1);
      else if (k.length === 1 && '0123456789.-'.includes(k) && customFields[customActive].length < 14) customFields[customActive] += k;
      else return;
      ev.preventDefault();
      return;
    }
    if (k === ' ') { paused = !paused; syncClock(); }
    else if (k === 'g' || k === 'G') showGroundTrack = !showGroundTrack;
    else if (k === 'p' || k === 'P') { perturbations = !perturbations; physicsChanged(); }
    else if (k === 'm' || k === 'M') { useMascons = !useMascons; physicsChanged(); }
    else if (k === 'v' || k === 'V') showMascons = !showMascons;
    else if (k === 'e' || k === 'E') {
      const s = player.sampleAt(timeElapsed);
      if (s) camera.setView(...xyzToLatlon(s.earth));
    } else return;
    ev.preventDefault();
  }
  overlay.addEventListener('pointerdown', onMouseDown);
  overlay.addEventListener('pointerup', onMouseUp);
  overlay.addEventListener('pointermove', onMouseMove);
  overlay.addEventListener('wheel', onWheel, { passive: false });

  // --- symulacja (neworb.py:1295-1328) ---
  function step(dtReal) {
    if (crashed || paused || !player.samples.length) return;
    const simDt = slider.val * dtReal;
    let target = timeElapsed + simDt;
    const end = player.bufferedUntil;
    if (target >= end) {
      if (player.status !== 'ok') {
        crashed = true;
        crashReason = player.statusMessage ?? player.status;
      }
      target = end;   // przy statusie ok: czekamy na kolejną paczkę
    }
    if (target > timeElapsed) {
      player.advanceHistory(target, R_MOON, R_ESCAPE);
      timeElapsed = target;
      player.trimBefore(timeElapsed);
      const st = player.sampleAt(timeElapsed);
      historyAlt.push(norm(st.pos) - R_MOON);
      historyVel.push(norm(inertialVelocity(st.pos, st.vel)));
      if (historyAlt.length > MAX_HISTORY) { historyAlt.shift(); historyVel.shift(); }
    }
    // dociąganie kolejnej paczki
    if (!inflight && player.status === 'ok' && player.bufferedUntil - timeElapsed < Math.max(slider.val * 3, 300)) {
      requestChunk(player.samples[player.samples.length - 1]);
    }
  }

  // --- rysowanie (neworb.py:1336-1551) ---
  function render() {
    const { width, height } = layout;
    slider.y = height - 48;
    const panelX = Math.max(650, Math.trunc(width * 0.55));
    const panelW = Math.max(250, width - panelX - 25);
    const panelTop = 75;
    const panelH = Math.max(300, height - 100);
    Object.assign(layout, { panelX, panelW, panelTop, panelH });
    const viewCx = Math.trunc(panelX * 0.48);
    const viewCy = Math.trunc(height * 0.53);
    const focal = Math.min(panelX, height) * 0.92;

    const st = player.sampleAt(timeElapsed);
    const pos = st?.pos ?? null;
    const vel = st?.vel ?? null;
    const sunBody = st?.sun ?? null;
    const earthBody = st?.earth ?? null;
    const sunDir = sunBody ? sunBody.map((x) => x / norm(sunBody)) : null;
    const subsolar = sunBody ? xyzToLatlon(sunBody) : null;
    const subearth = earthBody ? xyzToLatlon(earthBody) : null;

    if (fitPending && st) {
      // orbit_extent: max(|r|, R + ha), ucieczka → R_ESCAPE
      const r = norm(pos);
      const rMax = st.ecc >= 1.0 || st.ha == null ? R_ESCAPE : Math.min(R_ESCAPE, Math.max(r, R_MOON + st.ha));
      camera.dist = Math.min(OrbitCamera.MAX_DIST, Math.max(6000.0, rMax * (1.0 + focal / (0.42 * height))));
      fitPending = false;
    }

    const tm = performance.now();
    moon.render({ camera, center: [viewCx, viewCy], focal, sunDir, panelX, height });
    perf.moon += performance.now() - tm;
    ctx.clearRect(0, 0, width, height);
    // tło panelu (poza widokiem 3D) jak screen.fill((10, 13, 20))
    ctx.fillStyle = rgb([10, 13, 20]);
    ctx.fillRect(panelX, 0, width - panelX, height);

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, panelX, height);
    ctx.clip();
    const radius = camera.apparentRadius(focal);
    if (radius < 2) circle(ctx, [145, 145, 150], viewCx, viewCy, Math.max(1, Math.trunc(radius)));
    else if (moon.levels) circle(ctx, [175, 180, 190], viewCx, viewCy, Math.trunc(radius), 1);
    const labelBounds = { x: 0, y: 62, w: panelX - 10, h: height - 62 - 80 };
    const fits = (x, y, w, h) => x >= labelBounds.x && y >= labelBounds.y && x + w <= labelBounds.x + labelBounds.w && y + h <= labelBounds.y + labelBounds.h;

    // siatka i punkty orientacyjne (neworb.py:855-881)
    if (radius >= 25) {
      for (const lineP of GRID) {
        const { sx, sy } = camera.project(lineP, viewCx, viewCy, focal);
        drawRuns(ctx, rgb([95, 155, 175]), sx, sy, camera.visible(lineP));
      }
      const { sx, sy } = camera.project(LANDMARK_XYZ, viewCx, viewCy, focal);
      const vis = camera.visible(LANDMARK_XYZ);
      catalog.landmarks.forEach((lm, i) => {
        if (!vis[i]) return;
        const x = Math.trunc(sx[i]);
        const y = Math.trunc(sy[i]);
        circle(ctx, [8, 12, 18], x, y, 5);
        circle(ctx, lm.color_rgb, x, y, 3);
        if (radius < 120) return;
        const { w, h } = textSize(ctx, lm.name, FONT);
        const lx = x + 7;
        const ly = y - Math.trunc(h / 2);
        if (fits(lx, ly, w + 1, h + 1)) {
          text(ctx, lm.name, [5, 8, 12], lx + 1, ly + 1, FONT);
          text(ctx, lm.name, lm.color_rgb, lx, ly, FONT);
        }
      });
    }
    // mascony (neworb.py:833-852)
    if (showMascons && radius >= 35) {
      for (const ring of RINGS) {
        const { sx, sy } = camera.project(ring.pts, viewCx, viewCy, focal);
        drawRuns(ctx, rgb([255, 110, 145]), sx, sy, camera.visible(ring.pts));
        if (radius >= 110 && camera.visible(ring.center)[0]) {
          const p = camera.project(ring.center, viewCx, viewCy, focal);
          const x = Math.trunc(p.sx[0]);
          const y = Math.trunc(p.sy[0]);
          circle(ctx, [255, 110, 145], x, y, 2);
          const { w, h } = textSize(ctx, ring.name, FONT_SMALL);
          const lx = x + 6;
          const ly = y - Math.trunc(h / 2);
          if (fits(lx, ly, w + 1, h + 1)) {
            text(ctx, ring.name, [5, 8, 12], lx + 1, ly + 1, FONT_SMALL);
            text(ctx, ring.name, [255, 150, 175], lx, ly, FONT_SMALL);
          }
        }
      }
    }
    const track = player.view();
    const nTrack = track.length / 4;
    if (showGroundTrack && nTrack > 1) {
      const ground = new Float64Array(nTrack * 3);
      for (let i = 0; i < nTrack; i++) {
        const r = Math.hypot(track[i * 4], track[i * 4 + 1], track[i * 4 + 2]);
        for (let k = 0; k < 3; k++) ground[i * 3 + k] = (track[i * 4 + k] / r) * R_MOON * 1.003;
      }
      const { sx, sy } = camera.project(ground, viewCx, viewCy, focal);
      drawRuns(ctx, rgb([255, 170, 60]), sx, sy, camera.visible(ground), null, 2);
    }
    for (const [point, marker] of [[sunBody, drawSunMarker], [earthBody, drawEarthMarker]]) {
      if (point && radius >= 25) {
        const n = norm(point);
        const surf = point.map((x) => (x / n) * R_MOON * 1.01);
        if (camera.visible(surf)[0]) {
          const p = camera.project(surf, viewCx, viewCy, focal);
          marker(ctx, Math.trunc(p.sx[0]), Math.trunc(p.sy[0]), 7);
        }
      }
    }
    if (nTrack > 1) {
      const { sx, sy } = camera.project(track, viewCx, viewCy, focal, 4);
      drawRuns(ctx, rgb([100, 200, 255]), sx, sy, camera.visible(track, 4));
    }
    if (pos) {
      const satVisible = !!camera.visible(pos)[0];
      const sp = camera.project(pos, viewCx, viewCy, focal);
      const satXY = [Math.trunc(sp.sx[0]), Math.trunc(sp.sy[0])];
      const rn = norm(pos);
      const nadir = pos.map((x) => (x / rn) * R_MOON * 1.003);
      if (showGroundTrack && camera.visible(nadir)[0]) {
        const np = camera.project(nadir, viewCx, viewCy, focal);
        const nadirXY = [Math.trunc(np.sx[0]), Math.trunc(np.sy[0])];
        if (satVisible) line(ctx, [200, 200, 120], satXY[0], satXY[1], nadirXY[0], nadirXY[1]);
        circle(ctx, [10, 10, 10], nadirXY[0], nadirXY[1], 5);
        circle(ctx, [255, 170, 60], nadirXY[0], nadirXY[1], 4, 2);
      }
      if (satVisible) {
        circle(ctx, crashed ? [255, 80, 80] : [255, 220, 80], satXY[0], satXY[1], 6);
        text(ctx, 'Probe', [255, 255, 255], satXY[0] + 10, satXY[1] - 10, FONT);
      }
    }
    ctx.restore();

    roundRect(ctx, [10, 13, 20], 0, height - 86, panelX, 86, 0, 0, 170 / 255);
    presets.forEach(([label, key], i) => {
      const r = presetRect(i);
      const active = currentPreset === key || (key === 'CUSTOM' && currentPreset === 'Custom');
      roundRect(ctx, active ? [50, 120, 190] : [30, 36, 48], r.x, r.y, r.w, r.h, 6);
      roundRect(ctx, [80, 150, 230], r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1, 6, 1);
      const { w } = textSize(ctx, label, FONT);
      text(ctx, label, [240, 245, 255], r.x + r.w / 2 - Math.trunc(w / 2), r.y + 9, FONT);
    });
    // skróty klawiszowe zawijane w szerokości paska (do panelu telemetrii), a nie ucinane pod nim
    const helpRows = wrapLines(ctx, HELP, Math.max(120, panelX - 365), FONT_SMALL, '  ');
    const helpTop = height - 86 + Math.max(4, Math.trunc((86 - helpRows.length * 17) / 2));
    helpRows.forEach((l, i) => text(ctx, l, [150, 160, 175], 355, helpTop + i * 17, FONT_SMALL));

    // panel telemetrii (neworb.py:1404-1463)
    roundRect(ctx, [16, 20, 28], panelX, panelTop, panelW, panelH, 8);
    roundRect(ctx, [45, 55, 75], panelX + 0.5, panelTop + 0.5, panelW - 1, panelH - 1, 8, 1);
    const lines = [['--- TELEMETRY ---', [210, 215, 225]], [`Preset: ${currentPreset}`, [210, 215, 225]]];
    let period = 7 * 86400.0;
    if (st) {
      const altitude = norm(pos) - R_MOON;
      const vIn = inertialVelocity(pos, vel);
      const speed = norm(vIn);
      const [subLat, subLon] = xyzToLatlon(pos);
      const rDir = pos.map((x) => x / norm(pos));
      const sunElev = Math.asin(Math.max(-1, Math.min(1, dot(rDir, sunDir)))) / DEG;
      const along = dot(pos, sunDir);
      const inShadow = along < 0 && norm(pos.map((x, k) => x - along * sunDir[k])) < R_MOON;
      const timeLine = `UTC: ${fmtUtc(epochMs + timeElapsed * 1000)}   T+${(timeElapsed / 3600.0).toFixed(2)} h`;
      const lightLine = `Sun above subsat. pt: ${fmtSigned(sunElev, 1, 5)}° (${sunElev > 0 ? 'day' : 'night'})  probe: ${inShadow ? 'in shadow' : 'in sunlight'}`;
      let masconLine;
      let masconCol;
      if (useMascons) {
        const tag = st.nearest ? ` [${st.nearest}]` : '';
        masconLine = `Mascon anomaly: ${fmtSigned(st.dgR, 1, 6)} mGal (horiz. ${fmtWidth(st.dgH, 1, 5)})${tag}`;
        masconCol = Math.abs(st.dgR) > 25.0 ? [255, 145, 175] : [210, 215, 225];
      } else {
        masconLine = 'Mascon anomaly: OFF (press M)';
        masconCol = [140, 150, 165];
      }
      const haStr = st.ha == null ? '∞' : fmtComma(st.ha, 1);
      let model = 'monopole + J2';
      if (useMascons) model += ' + C22/J3/J4 + 14 mascons';
      if (perturbations) model += ' + Earth + Sun';
      const statusText = paused && !crashed ? 'PAUSED' : (crashed ? crashReason : 'RUNNING');
      lines.push(
        [timeLine, [210, 215, 225]],
        [`Altitude: ${fmtComma(altitude, 2)} km   Speed: ${speed.toFixed(4)} km/s`, [210, 215, 225]],
        [`Osc. orbit: ${fmtComma(st.hp, 1)} × ${haStr} km   e = ${st.ecc.toFixed(5)}`, [150, 220, 255]],
        [`Subsatellite point: ${fmtSigned(subLat, 3, 8)}°  ${fmtSigned(subLon, 3, 9)}°`, [255, 190, 110]],
        [masconLine, masconCol],
        [lightLine, [210, 215, 225]],
        [`Model: ${model}`, [210, 215, 225]],
        [`Status: ${statusText}`, crashed ? [255, 105, 105] : [210, 215, 225]],
      );
      if (norm(pos) > R_MOON) {
        const energy = 0.5 * dot(vIn, vIn) - GM / norm(pos);
        period = energy < 0 ? 2 * Math.PI * Math.sqrt((-GM / (2 * energy)) ** 3 / GM) : 7 * 86400.0;
      }
    } else {
      lines.push([netError || 'Loading orbit…', netError ? [255, 105, 105] : [210, 215, 225]]);
    }
    if (st && netError) lines.push([netError, [255, 105, 105]]);
    lines.forEach(([l, col], i) => text(ctx, l, col, panelX + 16, panelTop + 12 + i * 19, FONT));

    // mapa toru (neworb.py:1465-1484)
    const panelBottom = panelTop + panelH;
    const mapTitleY = panelTop + 12 + lines.length * 19 + 6;
    let mapW = panelW - 32;
    let mapH = Math.trunc(mapW / 2);
    const avail = panelBottom - (mapTitleY + 22) - 175;
    if (mapH > avail) { mapH = Math.max(60, avail); mapW = 2 * mapH; }
    const mapRect = { x: panelX + 16, y: mapTitleY + 22, w: mapW, h: mapH };
    text(ctx, 'Ground track [lat/lon]', [180, 200, 220], panelX + 16, mapTitleY, FONT_BOLD);
    if (trackMap && pos) {
      trackMap.draw(ctx, mapRect, track, timeElapsed, Math.min(period, 7 * 86400.0), pos, sunDir, subsolar, subearth, catalog, showMascons);
    }

    // wykresy (neworb.py:1520-1525)
    const chartsY = mapRect.y + mapRect.h + 22;
    const chartH = Math.max(50, Math.min(170, panelBottom - chartsY - 34));
    const chartW = Math.trunc((panelW - 32 - 12) / 2);
    drawChart(ctx, 'Altitude [km]', historyAlt, panelX + 16, chartsY, chartW, chartH, [80, 220, 140], 'km');
    drawChart(ctx, 'Speed [km/s]', historyVel, panelX + 28 + chartW, chartsY, chartW, chartH, [250, 160, 60], 'km/s');

    // suwak tempa (TimeSlider.draw)
    roundRect(ctx, [50, 60, 75], slider.x, slider.y, slider.w, slider.h, 4);
    const ratio = Math.max(0, Math.min(1, Math.log(slider.val / slider.min) / Math.log(slider.max / slider.min)));
    const fillW = Math.trunc(slider.w * ratio);
    if (fillW > 0) roundRect(ctx, [80, 150, 220], slider.x, slider.y, fillW, slider.h, 4);
    circle(ctx, [240, 245, 255], slider.x + fillW, slider.y + slider.h / 2, 7);
    text(ctx, `${slider.label}: ${fmtComma(slider.val, 1)}x`, [220, 225, 235], slider.x, slider.y - 22, FONT);

    if (customDialog) drawCustomDialog(width, height);
  }

  function drawCustomDialog(width, height) {
    ctx.fillStyle = 'rgba(0,0,0,0.686)';
    ctx.fillRect(0, 0, width, height);
    const dl = dialogLayout();
    const { box, inner } = dl;
    roundRect(ctx, [22, 29, 42], box.x, box.y, box.w, box.h, 10);
    roundRect(ctx, [90, 135, 185], box.x + 1, box.y + 1, box.w - 2, box.h - 2, 10, 2);
    text(ctx, 'Custom orbit', [240, 245, 255], inner.x, dl.titleY, FONT_BOLD);
    ['Altitude [km]', 'Inclination [deg]', 'Speed [km/s]'].forEach((label, fi) => {
      const r = dl.fields[fi];
      const active = fi === customActive;
      text(ctx, label, [205, 215, 230], r.x, r.y - 22, FONT);
      roundRect(ctx, active ? [45, 58, 76] : [30, 38, 52], r.x, r.y, r.w, r.h, 5);
      if (active) roundRect(ctx, [150, 200, 245], r.x + 1, r.y + 1, r.w - 2, r.h - 2, 5, 2);
      else roundRect(ctx, [100, 165, 225], r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1, 5, 1);
      text(ctx, customFields[fi], [255, 255, 255], r.x + 12, r.y + 10, FONT_BOLD);
    });
    const f0 = customFields[0];
    // Python: custom_fields[0].replace('.', '', 1).isdigit() and float(custom_fields[0]) > 0
    const v0 = /^\d+$/.test(f0.replace('.', '')) && Number(f0) > 0 ? circularSpeed(Number(f0)) : 0.0;
    text(ctx, `Circular speed: ${v0.toFixed(4)} km/s`, [120, 220, 160], inner.x, dl.suggestY, FONT);
    for (const [r, label, fill] of [[dl.apply, 'Apply', [45, 115, 80]], [dl.cancel, 'Cancel', [65, 75, 95]]]) {
      roundRect(ctx, fill, r.x, r.y, r.w, r.h, 5);
      const { w, h } = textSize(ctx, label, FONT);
      text(ctx, label, [255, 255, 255], r.x + Math.round((r.w - w) / 2), r.y + Math.round((r.h - h) / 2), FONT);
    }
    const msgColor = customError ? [255, 120, 120] : [175, 185, 200];
    dl.msg.rows.forEach((row, i) => text(ctx, row, msgColor, inner.x, dl.msg.y + i * dl.msg.lineH, dl.msg.font));
  }

  // --- pętla ---
  let raf = 0;
  let lastFrame = 0;
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dtReal = lastFrame ? Math.min((now - lastFrame) / 1000, 0.05) : 0;
    lastFrame = now;
    const before = timeElapsed;
    const t0 = performance.now();
    step(dtReal);
    const t1 = performance.now();
    if (timeElapsed !== before) syncClock();
    const t2 = performance.now();
    render();
    const t3 = performance.now();
    perf.step += t1 - t0; perf.clock += t2 - t1; perf.render += t3 - t2; perf.frames += 1;
  }
  const perf = { step: 0, clock: 0, render: 0, moon: 0, frames: 0 };

  function resize() {
    const r = root.getBoundingClientRect();
    layout.width = Math.max(1, Math.round(r.width));
    layout.height = Math.max(1, Math.round(r.height));
    const dpr = Math.min(window.devicePixelRatio, 2);
    moon.setSize(layout.width, layout.height);
    overlay.width = Math.round(layout.width * dpr);
    overlay.height = Math.round(layout.height * dpr);
    overlay.style.width = `${layout.width}px`;
    overlay.style.height = `${layout.height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  const ro = new ResizeObserver(resize);

  let started = false;
  let pausedOnLeave = false;
  root._debug = {
    camera, player, slider, perf,
    /** Synchroniczny pomiar kosztu klatki (render + gl.finish), niezależny od dławienia rAF. */
    bench(n = 20) {
      const gl = root.querySelector('canvas.orbit-gl').getContext('webgl2');
      const t0 = performance.now();
      for (let i = 0; i < n; i++) { render(); gl.finish(); }
      return (performance.now() - t0) / n;
    },
    get state() { return { timeElapsed, crashed, crashReason, paused, currentPreset, useMascons, perturbations, epochMs, historyLen: historyAlt.length }; },
    resetSim, applyCustom,
  };

  return {
    activate() {
      ro.observe(root);
      resize();
      window.addEventListener('keydown', onKey);
      clock.addEventListener('timechange', onTime);
      clock.addEventListener('playstatechange', onPlay);
      if (!started) {
        started = true;
        epochMs = clock.t;
        paused = false;
        resetSim('LRO');
      } else {
        paused = pausedOnLeave;
        if (Math.abs(clock.t - (epochMs + timeElapsed * 1000)) > 1000) {
          epochMs = clock.t;   // czas zmieniony w innym trybie → nowa epoka jak --epoch
          resetSim();
        } else {
          syncClock();
        }
      }
      lastFrame = 0;
      raf = requestAnimationFrame(frame);
    },
    deactivate() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener('keydown', onKey);
      clock.removeEventListener('timechange', onTime);
      clock.removeEventListener('playstatechange', onPlay);
      // Zegar strony grał w tempie orbity; drugi tryb startuje zatrzymany (jak newlunar),
      // a po powrocie orbita wraca do swojego stanu pauzy.
      pausedOnLeave = paused;
      if (clock.playing) { selfClock = true; clock.pause(); selfClock = false; }
    },
  };
}
