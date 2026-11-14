// Tryb „Powierzchnia” — port newlunar.py: widok z powierzchni Księżyca.
// Dane: lunar_surface.terrain (siatka terenu + horyzont) i lunar_surface.sky (Ziemia, Słońce, zaćmienia).
// Sterowanie, suwaki, klawisze i HUD odwzorowują newlunar.main() (newlunar.py:1733-2133).
import * as THREE from 'three';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';

import { buildTerrainMesh, enuToScene } from './terrain-mesh.js';
import { createSky } from './sky-bodies.js';

const DEG = Math.PI / 180;
const TWO_PI = 2 * Math.PI;
const BASE_FOV = 75 * DEG;            // pionowe pole widzenia (focal = (ch/2)/tan(fov/2))
const MIN_FOV = 0.2 * DEG;
const MAX_FOV = 115 * DEG;
const PLAY_SPEED = 24;                // indeksów godzinowych na sekundę (newlunar.py:1759)
const HOUR_MS = 3_600_000;
const SKY_MIN_INTERVAL_MS = 200;
const TERRAIN_DEBOUNCE_MS = 250;

// newlunar.py:1836-1842
const PRESETS = {
  1: ['Krater Tycho', -43.31, -11.36],
  2: ['Krater Kopernik', 9.62, -20.08],
  3: ['Krater Shackleton (Biegun S)', -89.60, 0.00],
  4: ['Apollo 11 (Mare Tranquillitatis)', 0.67, 23.47],
  5: ['Mare Orientale', -19.40, -92.80],
};

const pad = (s, w) => String(s).padStart(w);
const fixed = (v, d) => (Object.is(v, -0) ? 0 : v).toFixed(d);
const signed = (v, d, w = 0) => pad((v >= 0 ? '+' : '') + fixed(v, d), w);
const wrapPi = (a) => ((a + Math.PI) % TWO_PI + TWO_PI) % TWO_PI - Math.PI;

/** newlunar.format_height_m */
export function formatHeightM(m) {
  return m < 1000 ? `${m.toFixed(1)} m` : `${(m / 1000).toFixed(2)} km`;
}

const yearStartMs = (y) => Date.UTC(y, 0, 1);
/** Liczba wierszy coords/<rok>.csv: godziny roku; 2100.csv ma jeden wiersz. */
const yearRows = (y) => (y >= 2100 ? 1 : (yearStartMs(y + 1) - yearStartMs(y)) / HOUR_MS);
const fmtUtc = (ms) => new Date(ms).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';

/** Suwak DOM o semantyce newlunar.Slider (wartość = min + ratio^power · (max − min)). */
function makeSlider(parent, { label, min, max, value, power = 1, isInt = false, format }) {
  const wrap = document.createElement('label');
  wrap.className = 'sim-slider';
  const text = document.createElement('span');
  const input = document.createElement('input');
  input.type = 'range';
  input.min = '0';
  input.max = '1';
  input.step = 'any';
  wrap.append(text, input);
  parent.append(wrap);
  const s = {
    min, max, power, isInt, value, label, format, el: wrap, input,
    toRatio(v) {
      return s.max > s.min ? Math.max(0, Math.min(1, (v - s.min) / (s.max - s.min))) ** (1 / s.power) : 0;
    },
    set(v, custom) {
      s.value = v;
      input.value = String(s.toRatio(v));
      s.render(custom);
    },
    render(custom) {
      const str = custom ?? (s.isInt ? String(Math.trunc(s.value)) : s.format(s.value));
      text.textContent = `${s.label}: ${str}`;
    },
    onInput: null,
  };
  // Suwak nie zatrzymuje fokusu (w pygame suwaki nie przejmują klawiatury): po puszczeniu
  // myszy skróty (spacja, 1–5, E, S…) działają od razu.
  input.addEventListener('change', () => input.blur());
  input.addEventListener('pointerup', () => input.blur());
  input.addEventListener('input', () => {
    const v = s.min + Number(input.value) ** s.power * (s.max - s.min);
    s.value = s.isInt ? Math.round(v) : v;
    s.render();
    s.onInput?.(s.value);
  });
  s.set(value);
  return s;
}

export function createSurfaceMode({ root, api, endpoint, clock }) {
  root.innerHTML = '';
  const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x05070c);  // (5, 7, 12) jak screen.fill w newlunar
  root.append(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(BASE_FOV / DEG, 1, 0.0005, 20000);
  camera.position.set(0, 0, 0);
  const sky = createSky(scene, renderer);
  api.getJson(endpoint('lunar_surface.stars'), {}, { cache: true })
    .then((f) => sky.setStars(f))
    .catch((err) => setStatus(`Błąd gwiazd: ${err?.message ?? err}`));

  // --- stan (newlunar.py:1746-1772) ---
  let camAz = 0;
  let camAlt = 15 * DEG;
  let fov = BASE_FOV;
  let targetFov = BASE_FOV;
  let wireframe = false;
  let showHorizonLine = true;
  let locationName = 'Krater Tycho';
  let statusMsg = '';
  let statusTimer = 0;
  let animTime = 0;
  let animFrozen = false;   // tylko debug: stały czas animacji chmur do porównań z pygame

  // --- panele DOM ---
  const topLeft = document.createElement('div');
  topLeft.className = 'sim-panel surface-observer';
  const bottom = document.createElement('div');
  bottom.className = 'sim-panel surface-time';
  const presetBar = document.createElement('div');
  presetBar.className = 'sim-buttons';
  for (const [key, [name]] of Object.entries(PRESETS)) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = `${key}. ${name}`;
    b.addEventListener('click', () => applyPreset(key));
    presetBar.append(b);
  }
  const hud = document.createElement('div');
  hud.className = 'sim-panel sim-hud surface-hud';
  const hudText = document.createElement('div');
  const hudStatus = document.createElement('div');
  hudStatus.className = 'sim-status';
  hud.append(hudText, hudStatus);
  const labels = document.createElement('div');
  labels.className = 'surface-labels';
  root.append(labels, topLeft, bottom, hud);

  const deg2 = (v) => `${signed(v, 2)}°`;
  const sLat = makeSlider(topLeft, { label: 'Szerokość (Lat)', min: -90, max: 90, value: -43.31, format: deg2 });
  const sLon = makeSlider(topLeft, { label: 'Długość (Lon)', min: -180, max: 180, value: -11.36, format: deg2 });
  const sHeight = makeSlider(topLeft, { label: 'Wysokość nad pow.', min: 2, max: 50000, value: 2, power: 3, format: formatHeightM });
  topLeft.append(presetBar);
  const sYear = makeSlider(bottom, { label: 'Rok', min: 2000, max: 2100, value: 2000, isInt: true });
  const sTime = makeSlider(bottom, { label: 'Czas w roku', min: 0, max: 1, value: 0, format: (v) => v.toFixed(2) });

  // --- czas: wspólny zegar ↔ (rok, indeks godzinowy) ---
  const timeParts = (ms) => {
    const y = new Date(ms).getUTCFullYear();
    return { year: y, idx: (ms - yearStartMs(y)) / HOUR_MS };
  };
  const syncTimeSliders = () => {
    const { year, idx } = timeParts(clock.t);
    sYear.set(year);
    sTime.max = Math.max(0, yearRows(year) - 1);
    sTime.set(Math.min(idx, sTime.max), fmtUtc(clock.t));
  };
  sYear.onInput = (year) => {
    // newlunar.py:1931-1934: nowy rok, indeks przycięty do jego zakresu
    const idx = Math.min(timeParts(clock.t).idx, Math.max(0, yearRows(year) - 1));
    clock.seek(yearStartMs(year) + idx * HOUR_MS);
  };
  sTime.onInput = (idx) => clock.seek(yearStartMs(sYear.value) + idx * HOUR_MS);
  sLat.onInput = sLon.onInput = () => { locationName = 'Własne współrzędne'; observerChanged(); };
  sHeight.onInput = () => observerChanged();

  const observer = () => ({ lat_deg: sLat.value, lon_deg: sLon.value, eye_height_m: sHeight.value });

  // --- dane z backendu ---
  let patch = null;
  let terrainGroup = null;
  let terrainAbort = null;
  let terrainTimer = null;
  let terrainLoading = false;
  let skyPrev = null;
  let skyCurr = null;
  let skyAbort = null;
  let skyLastReq = 0;
  let skyReqKey = '';
  let skyObsKey = '';

  const obsKey = () => `${sLat.value}|${sLon.value}|${sHeight.value}`;

  let obsChangedAt = 0;
  let skyInflightObs = null;

  function observerChanged() {
    obsChangedAt = performance.now();
    clearTimeout(terrainTimer);
    terrainTimer = setTimeout(loadTerrain, TERRAIN_DEBOUNCE_MS);
  }

  async function loadTerrain() {
    terrainAbort?.abort();
    const ctrl = new AbortController();
    terrainAbort = ctrl;
    terrainLoading = true;
    const reqObs = obsKey();
    let retrying = false;
    try {
      const p = await api.getJson(endpoint('lunar_surface.terrain'), observer(), { signal: ctrl.signal });
      if (ctrl.signal.aborted) return;
      if (terrainGroup) {
        scene.remove(terrainGroup);
        terrainGroup.userData.dispose();
      }
      patch = p;
      terrainGroup = buildTerrainMesh(p);
      terrainGroup.userData.setWireframe(wireframe);
      scene.add(terrainGroup);
      sky.setHorizon(p.horizon);
      rebuildHorizonLine();
    } catch (err) {
      if (err?.name === 'AbortError') return;
      // 503: teren przeliczany dla innego zapytania — ponów, jeśli obserwator się nie zmienił
      if (err?.status === 503 && reqObs === obsKey()) {
        retrying = true;
        clearTimeout(terrainTimer);
        terrainTimer = setTimeout(loadTerrain, 1000);
        return;
      }
      setStatus(`Błąd terenu: ${err?.message ?? err}`);
    } finally {
      if (terrainAbort === ctrl && !retrying) terrainLoading = false;
    }
  }

  /**
   * Niebo: jedno żądanie naraz. Zmiana czasu nie przerywa żądania w locie — po odpowiedzi
   * następna klatka pyta o bieżący czas. Przerywamy tylko przy zmianie obserwatora, a o nowego
   * obserwatora pytamy dopiero, gdy przestanie się zmieniać (jak debounce terenu).
   */
  function maybeFetchSky(now) {
    const reqObs = obsKey();
    if (skyAbort && skyInflightObs !== reqObs) { skyAbort.abort(); skyAbort = null; }
    if (skyAbort) return;
    if (now - obsChangedAt < TERRAIN_DEBOUNCE_MS) return;
    const key = `${clock.t}|${reqObs}`;
    if (key === skyReqKey || now - skyLastReq < SKY_MIN_INTERVAL_MS) return;
    skyReqKey = key;
    skyLastReq = now;
    const ctrl = new AbortController();
    skyAbort = ctrl;
    skyInflightObs = reqObs;
    const t = new Date(clock.t).toISOString();
    api.getJson(endpoint('lunar_surface.sky'), { t, ...observer() }, { signal: ctrl.signal })
      .then((s) => {
        if (ctrl.signal.aborted) return;
        s._tMs = Date.parse(s.t);
        // Interpolacja tylko między odpowiedziami dla tego samego obserwatora.
        skyPrev = reqObs === skyObsKey ? skyCurr : null;
        skyCurr = s;
        skyObsKey = reqObs;
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        skyReqKey = '';   // 503 / błąd sieci: ponów po SKY_MIN_INTERVAL_MS
        if (err?.status !== 503) setStatus(`Błąd nieba: ${err?.message ?? err}`);
      })
      .finally(() => { if (skyAbort === ctrl) skyAbort = null; });
  }

  // Obrót Ziemi między próbkami nieba: osie ECEF obracają się wokół osi Z z szybkością GMST
  // z newlunar.get_topocentric_vectors (360.98564736629°/dobę) — tylko interpolacja do rysowania.
  const EARTH_RATE = (360.98564736629 * DEG) / 86_400_000;   // rad/ms
  const rotateAxes = (A, dtMs) => {
    const th = EARTH_RATE * dtMs;
    const c = Math.cos(th);
    const s = Math.sin(th);
    const [x, y, z] = A;
    return [x.map((v, i) => c * v + s * y[i]), y.map((v, i) => -s * x[i] + c * v), z];
  };
  // Gram-Schmidt bez iloczynu wektorowego: baza [N, E, U] jest lewoskrętna, więc Z × X po
  // składowych dałoby −Y.
  const orthonormal = ([x, y, z]) => {
    const Z = new THREE.Vector3(...z).normalize();
    const X = new THREE.Vector3(...x);
    X.addScaledVector(Z, -X.dot(Z)).normalize();
    const Y = new THREE.Vector3(...y);
    Y.addScaledVector(Z, -Y.dot(Z)).addScaledVector(X, -Y.dot(X)).normalize();
    return [X.toArray(), Y.toArray(), Z.toArray()];
  };

  /** Stan nieba w chwili clock.t: liniowa inter/ekstrapolacja między dwiema ostatnimi odpowiedziami. */
  function skyAt(tMs) {
    if (!skyCurr) return null;
    if (!skyPrev || skyCurr._tMs === skyPrev._tMs) {
      return { ...skyCurr, earth_axes_enu: rotateAxes(skyCurr.earth_axes_enu, tMs - skyCurr._tMs), _f: 0, _base: skyCurr, _dtMs: 0 };
    }
    const f = Math.max(-1, Math.min(3, (tMs - skyPrev._tMs) / (skyCurr._tMs - skyPrev._tMs)));
    const lerp = (a, b) => a + (b - a) * f;
    const lv = (a, b) => a.map((x, i) => lerp(x, b[i]));
    const nv = (a, b) => { const v = lv(a, b); const l = Math.hypot(...v) || 1; return v.map((x) => x / l); };
    const body = (a, b) => ({
      ...b,
      dir_enu: nv(a.dir_enu, b.dir_enu),
      angular_radius_deg: lerp(a.angular_radius_deg, b.angular_radius_deg),
      distance_km: lerp(a.distance_km, b.distance_km),
    });
    const P = skyPrev;
    const C = skyCurr;
    const earth = body(P.earth, C.earth);
    const sun = body(P.sun, C.sun);
    for (const b of [earth, sun]) {
      const [n, e, u] = b.dir_enu;
      b.alt_deg = Math.asin(Math.max(-1, Math.min(1, u))) / DEG;
      b.az_deg = ((Math.atan2(e, n) / DEG) % 360 + 360) % 360;
    }
    sun.effective_visibility = lerp(P.sun.effective_visibility, C.sun.effective_visibility);
    return {
      ...C,
      earth,
      sun,
      eclipse_ring_factor: lerp(P.eclipse_ring_factor, C.eclipse_ring_factor),
      eclipse_red_glow: lerp(P.eclipse_red_glow, C.eclipse_red_glow),
      dark_side_exposure: lerp(P.dark_side_exposure, C.dark_side_exposure),
      sun_from_earth_enu: nv(P.sun_from_earth_enu, C.sun_from_earth_enu),
      moon_from_earth_enu_km: lv(P.moon_from_earth_enu_km, C.moon_from_earth_enu_km),
      ecliptic_to_enu: C.ecliptic_to_enu.map((row, i) => nv(P.ecliptic_to_enu[i], row)),
      sun_distance_from_earth_km: lerp(P.sun_distance_from_earth_km, C.sun_distance_from_earth_km),
      earth_axes_enu: orthonormal((() => {
        const Ap = rotateAxes(P.earth_axes_enu, tMs - P._tMs);
        const Ac = rotateAxes(C.earth_axes_enu, tMs - C._tMs);
        return Ac.map((row, i) => lv(Ap[i], row));
      })()),
      _f: f,
      _base: C,
      _dtMs: tMs - C._tMs,
    };
  }

  // --- horyzont (LunarTerrain3D.get_horizon_at_azimuth) ---
  function horizonAt(azRad) {
    if (!patch) return 0;
    const alt = patch.horizon.alt_deg;
    const n = alt.length;
    const x = (((azRad % TWO_PI) + TWO_PI) % TWO_PI) / TWO_PI * n;
    const i = Math.floor(x) % n;
    const f = x - Math.floor(x);
    return (alt[i] * (1 - f) + alt[(i + 1) % n] * f) * DEG;
  }

  // --- linia horyzontu (draw_3d: kolor (90,175,220), grubość 2 px, na wierzchu terenu) ---
  const horizonMat = new LineMaterial({ color: 0x5aafdc, linewidth: 2, depthTest: false, depthWrite: false });
  let horizonLine = null;
  function rebuildHorizonLine() {
    if (horizonLine) { scene.remove(horizonLine); horizonLine.geometry.dispose(); horizonLine = null; }
    if (!patch) return;
    const pts = [];
    const alt = patch.horizon.alt_deg;
    for (let i = 0; i <= alt.length; i++) {
      const az = (i % alt.length) * TWO_PI / alt.length;
      const a = alt[i % alt.length] * DEG;
      const v = enuToScene([Math.cos(a) * Math.cos(az), Math.cos(a) * Math.sin(az), Math.sin(a)]).multiplyScalar(3000);
      pts.push(v.x, v.y, v.z);
    }
    const g = new LineGeometry();
    g.setPositions(pts);
    horizonLine = new Line2(g, horizonMat);
    horizonLine.renderOrder = 10;
    horizonLine.frustumCulled = false;
    horizonLine.visible = showHorizonLine;
    scene.add(horizonLine);
  }

  // --- kamera (get_camera_basis, zoom_at_point) ---
  const size = { cw: 1, ch: 1 };
  function zoomAtPoint(factor, mx, my) {
    const old = targetFov;
    targetFov = Math.max(MIN_FOV, Math.min(MAX_FOV, targetFov * factor));
    if (Math.abs(targetFov - old) < 1e-9) return;
    const { cw, ch } = size;
    const fOld = (ch / 2) / Math.tan(old / 2);
    const fNew = (ch / 2) / Math.tan(targetFov / 2);
    const dx = mx - cw / 2;
    const dy = ch / 2 - my;
    camAz = (((camAz + (Math.atan2(dx, fOld) - Math.atan2(dx, fNew)) / Math.max(0.25, Math.cos(camAlt))) % TWO_PI) + TWO_PI) % TWO_PI;
    camAlt = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, camAlt + (Math.atan2(dy, fOld) - Math.atan2(dy, fNew))));
  }
  const fwdScene = new THREE.Vector3();
  function updateCamera() {
    camera.fov = fov / DEG;
    camera.aspect = size.cw / size.ch;
    camera.updateProjectionMatrix();
    enuToScene([Math.cos(camAlt) * Math.cos(camAz), Math.cos(camAlt) * Math.sin(camAz), Math.sin(camAlt)], fwdScene);
    camera.up.set(0, 1, 0);
    camera.lookAt(fwdScene);
  }

  function setStatus(msg) {
    statusMsg = msg;
    statusTimer = 3.5;
  }

  function applyPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    [locationName] = p;
    sLat.set(p[1]);
    sLon.set(p[2]);
    observerChanged();
  }

  function exportHorizonCsv() {
    if (!patch) return;
    const h = patch.horizon;
    const head = ['Azimuth_deg', 'Horizon_Altitude_deg', 'Horizon_Distance_km', 'Horizon_Lat_deg', 'Horizon_Lon_deg',
      'Horizon_Elevation_km', 'Observer_Lat_deg', 'Observer_Lon_deg', 'Observer_Elevation_km',
      'Observer_Height_above_surface_m'];
    const rows = [head.join(',')];
    const ob = patch.observer;
    for (let i = 0; i < h.alt_deg.length; i++) {
      rows.push([
        fixed(h.az_deg[i], 4), fixed(h.alt_deg[i], 6), fixed(h.distance_km[i], 4), fixed(h.lat_deg[i], 6),
        fixed(h.lon_deg[i], 6), fixed(h.elevation_km[i], 5), fixed(ob.lat_deg, 6), fixed(ob.lon_deg, 6),
        fixed(patch.observer_elevation_m / 1000, 5), fixed(patch.eye_height_m, 2),
      ].join(','));
    }
    const blob = new Blob([rows.join('\r\n') + '\r\n'], { type: 'text/csv' });   // csv.writer: \r\n
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'horizon.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    setStatus('Zapisano profil horyzontu: horizon.csv');
  }

  // --- wejście: mysz i klawiatura (newlunar.py:1870-1927) ---
  let dragging = false;
  let last = [0, 0];
  const canvas = renderer.domElement;
  canvas.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    dragging = true;
    last = [ev.clientX, ev.clientY];
    canvas.setPointerCapture(ev.pointerId);
  });
  canvas.addEventListener('pointerup', (ev) => { if (ev.button === 0) dragging = false; });
  canvas.addEventListener('pointermove', (ev) => {
    if (!dragging) return;
    const dx = ev.clientX - last[0];
    const dy = ev.clientY - last[1];
    last = [ev.clientX, ev.clientY];
    const sens = fov / size.ch;
    camAz = (((camAz - dx * sens) % TWO_PI) + TWO_PI) % TWO_PI;
    camAlt = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, camAlt + dy * sens));
  });
  canvas.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const steps = -Math.sign(ev.deltaY);
    if (!steps) return;
    const r = canvas.getBoundingClientRect();
    zoomAtPoint(0.80 ** steps, ev.clientX - r.left, ev.clientY - r.top);
  }, { passive: false });

  function onKey(ev) {
    if (ev.target instanceof HTMLInputElement || ev.target instanceof HTMLSelectElement) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const k = ev.key;
    const view = skyAt(clock.t);
    const { cw, ch } = size;
    if (k === ' ') {
      clock.toggle();
    } else if (k === '+' || k === '=' || ev.code === 'NumpadAdd') {
      zoomAtPoint(0.75, cw / 2, ch / 2);
    } else if (k === '-' || ev.code === 'NumpadSubtract') {
      zoomAtPoint(1 / 0.75, cw / 2, ch / 2);
    } else if (k === 'r' || k === 'R') {
      targetFov = BASE_FOV;
    } else if ((k === 'e' || k === 'E') && view) {
      const a = view.earth.alt_deg * DEG;
      const z = view.earth.az_deg * DEG;
      const dist = Math.hypot(camAlt - a, wrapPi(camAz - z));
      camAlt = a; camAz = z;
      if (dist < 2 * DEG) targetFov = 3.2 * DEG;
    } else if ((k === 's' || k === 'S') && view) {
      const a = view.sun.alt_deg * DEG;
      const z = view.sun.az_deg * DEG;
      const dist = Math.hypot(camAlt - a, wrapPi(camAz - z));
      camAlt = a; camAz = z;
      if (dist < 2 * DEG) targetFov = 1.4 * DEG;
    } else if (k === 'l' || k === 'L') {
      const hor = horizonAt(camAz);
      if (Math.abs(camAlt - hor) < 1.5 * DEG) targetFov = 8 * DEG;
      camAlt = hor;
    } else if (k === 'm' || k === 'M') {
      wireframe = !wireframe;
      terrainGroup?.userData.setWireframe(wireframe);
    } else if (k === 'h' || k === 'H') {
      showHorizonLine = !showHorizonLine;
      if (horizonLine) horizonLine.visible = showHorizonLine;
    } else if (k === 'c' || k === 'C') {
      exportHorizonCsv();
    } else if (PRESETS[k]) {
      applyPreset(k);
    } else {
      return;
    }
    ev.preventDefault();
  }

  // --- HUD (newlunar.py:2093-2121) ---
  function renderHud(view) {
    const zoom = BASE_FOV / fov;
    const lines = [
      `Lokacja: ${locationName} | DEM: ${patch?.dem_source ?? '—'} (SUB ${patch?.window_sub ?? 1}x)`,
      `Teren: ${signed((patch?.observer_elevation_m ?? 0) / 1000, 3)} km | Wys. obs.: ${formatHeightM(sHeight.value)} | Zoom: ${zoom.toFixed(1)}x`,
      `Kamera: Az ${fixed(camAz / DEG, 2)}° | Alt ${signed(camAlt / DEG, 2)}° (Hor: ${signed(horizonAt(camAz) / DEG, 2)}°)`,
      `Siatka terenu: ${patch ? `${patch.n_az}×${patch.n_r}` : '—'} (${terrainGroup?.userData.triangles ?? 0} trójkątów)`,
      '-'.repeat(62),
      view ? `ZIEMIA: Alt ${signed(view.earth.alt_deg, 2, 6)}° | Az ${pad(fixed(view.earth.az_deg, 2), 6)}° [${view._base.earth.status}]` : 'ZIEMIA: —',
      view ? `SŁOŃCE: Alt ${signed(view.sun.alt_deg, 2, 6)}° | Az ${pad(fixed(view.sun.az_deg, 2), 6)}° [${view._base.sun.status}]` : 'SŁOŃCE: —',
      '-'.repeat(62),
      '[Scroll / +/-] Zoom (do 375x) | [R] Reset zoomu | [Spacja] Play',
      '[E] Ziemia (2x = zoom) | [S] Słońce (2x = zoom) | [L] Horyzont',
      '[M] Siatka 3D | [H] Linia horyzontu | [C] Zapisz horizon.csv',
      '[1-5] Lokacje Księżyca',
    ];
    hudText.textContent = lines.join('\n');
    hudStatus.textContent = statusTimer > 0 ? statusMsg : (terrainLoading ? 'Wczytywanie terenu…' : '');
  }

  // --- pętla ---
  let raf = 0;
  let lastFrame = 0;
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = lastFrame ? Math.min(0.1, (now - lastFrame) / 1000) : 0;
    lastFrame = now;
    if (!animFrozen) animTime += dt;
    if (statusTimer > 0) statusTimer = Math.max(0, statusTimer - dt);

    if (clock.playing) {
      // newlunar.py:1936-1939: +24 indeksy/s, po końcu roku powrót do 0 w tym samym roku
      const { year, idx } = timeParts(clock.t);
      let next = idx + PLAY_SPEED * dt;
      if (next >= yearRows(year) - 1) next = 0;
      clock.seek(yearStartMs(year) + next * HOUR_MS);
    }
    fov += (targetFov - fov) * Math.min(1, 14 * dt);

    maybeFetchSky(now);
    const view = skyAt(clock.t);
    updateCamera();
    if (view) {
      const sunEff = view.sun.effective_visibility;
      terrainGroup?.userData.setLighting({
        sunDirScene: enuToScene(view.sun.dir_enu),
        sunEffVis: sunEff,
        earthAltRad: view.earth.alt_deg * DEG,
        redGlow: view.eclipse_red_glow,
      });
      sky.update(view, { camera, fov, size, camAlt, camAz, clockMs: clock.t, yearStartMs: yearStartMs(timeParts(clock.t).year), animTime, horizonAt, labels });
    }
    renderer.render(scene, camera);
    renderHud(view);
  }

  function resize() {
    const r = root.getBoundingClientRect();
    size.cw = Math.max(1, r.width);
    size.ch = Math.max(1, r.height);
    renderer.setSize(size.cw, size.ch, false);
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    horizonMat.resolution.set(size.cw, size.ch);
  }
  const ro = new ResizeObserver(resize);

  const onTime = () => syncTimeSliders();

  observerChanged();
  syncTimeSliders();
  // Uchwyt do debugowania w konsoli (jak window.modi na stronie głównej).
  root._debug = {
    scene, camera, renderer,
    get terrain() { return terrainGroup; },
    get patch() { return patch; },
    get sky() { return skyAt(clock.t); },
    setAnimTime(v) { animTime = v; animFrozen = true; },
    setCamera(altDeg, azDeg, fovDeg = BASE_FOV / DEG) {
      camAlt = altDeg * DEG; camAz = azDeg * DEG; fov = targetFov = fovDeg * DEG;
    },
  };

  return {
    activate() {
      ro.observe(root);
      resize();
      window.addEventListener('keydown', onKey);
      clock.addEventListener('timechange', onTime);
      syncTimeSliders();
      lastFrame = 0;
      skyReqKey = '';
      raf = requestAnimationFrame(frame);
    },
    deactivate() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener('keydown', onKey);
      clock.removeEventListener('timechange', onTime);
      skyAbort?.abort();
    },
  };
}
