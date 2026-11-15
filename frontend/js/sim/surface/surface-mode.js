// Tryb „Powierzchnia” — port geografia.py (silnik PQS na GPU) w surowym WebGL2, bez bibliotek 3D.
// Serwer liczy obserwatora (lunar_surface.observer: grunt, nachylenie, horyzont), niebo
// (lunar_surface.sky), gwiazdy (lunar_surface.stars) i wydaje kafle DEM/albedo; teren, gwiazdy,
// siatkę, Słońce i Ziemię rysuje GPU przeglądarki, a HUD canvas 2D (geografia.main(), geografia.py:2549-2998).
// Czas: wspólny SimulationClock strony (odchylenie 7), suwaki Year / Time of Year i Spacja jak w skrypcie.

import { makeSlider } from '../ui/slider.js';
import {
  cameraView, drawBodyLabel, drawCompass, drawHud, horizonCsv, hudLines, HUD_FONT, projectPoint,
} from './hud.js';
import { SkyRenderer } from './sky-renderer.js';
import { PATCH_N, TerrainRenderer, TAU_PX } from './terrain-renderer.js';
import { TileWindow } from './tile-window.js';

const DEG = Math.PI / 180;   // math.radians(x) = x · (π/180)
const TWO_PI = 2 * Math.PI;
// geografia.py:2570-2577, 2579-2580
const BASE_FOV = 75.0 * DEG;           // pionowe pole widzenia (focal = (ch/2)/tan(fov/2))
const MIN_FOV = 0.20 * DEG;
const MAX_FOV = 115.0 * DEG;
const PLAY_SPEED = 24.0;               // indeksów godzinowych na sekundę
const HOUR_MS = 3_600_000;
const SKY_MIN_INTERVAL_MS = 200;
const OBSERVER_DEBOUNCE_MS = 250;
const RETRY_MS = 1000;                 // ponowienie obserwatora/kafli/gwiazd po błędzie sieci
const MIN_TEXTURE_SIZE = 8192;         // albedo z pełnym pierścieniem: 32 × 256 px; Ziemia 8192 × 4096

const MSG_NO_WEBGL2 = 'Surface mode needs WebGL2, which this browser does not support.';
const MSG_CONTEXT_LOST = 'WebGL context lost. Reload the page.';

// geografia.py:2673-2679 — (Name, Lat_deg, Lon_deg, Initial_Azimuth_deg); klawisze K_1..K_5 (górny rząd)
const PRESETS = {
  Digit1: ['Tycho Crater', -43.31, -11.36, 15.0],
  Digit2: ['Copernicus Crater', 9.62, -20.08, 35.0],
  Digit3: ['Shackleton (Crater)', -89.48, 129.80, 0.0],
  Digit4: ['Vallis Alpes (Alpine Valley)', 48.65, 3.50, 56.0],
  Digit5: ['Apollo 11 (Mare Tranquillitatis)', 0.67, 23.47, 270.0],
};

const fixed = (v, d) => (Object.is(v, -0) ? 0 : v).toFixed(d);
const signed = (v, d) => (v >= 0 ? '+' : '') + fixed(v, d);
/** a % T jak w Pythonie (wynik ze znakiem dzielnika, -0.0 → +0.0). */
const pyMod = (a, T) => {
  const r = a % T;
  return r < 0 ? r + T : (r === 0 ? 0 : r);
};
const mod2pi = (a) => pyMod(a, TWO_PI);

// geografia.py:2543-2546
/** geografia.format_height_m */
export function formatHeightM(m) {
  return m < 1000 ? `${m.toFixed(1)} m` : `${(m / 1000).toFixed(2)} km`;
}

// --- czas: wspólny zegar ↔ (rok, ułamkowy indeks godzinowy coords/<rok>.csv), jak poprzedni port ---
const yearStartMs = (y) => Date.UTC(y, 0, 1);
/** Liczba wierszy coords/<rok>.csv: godziny roku; 2100.csv ma jeden wiersz. */
const yearRows = (y) => (y >= 2100 ? 1 : (yearStartMs(y + 1) - yearStartMs(y)) / HOUR_MS);
const timeParts = (ms) => {
  const y = new Date(ms).getUTCFullYear();
  return { year: y, idx: (ms - yearStartMs(y)) / HOUR_MS };
};
/** data["time"].strftime("%Y-%m-%d %H:%M UTC") */
const fmtUtc = (ms) => `${new Date(ms).toISOString().slice(0, 16).replace('T', ' ')} UTC`;

/** Komunikaty w #sim-error: widoczne tylko, gdy tryb Powierzchnia jest aktywny. */
function pageError() {
  const el = () => document.getElementById('sim-error');
  return {
    show(msg) {
      const e = el();
      if (!e || !msg) return;
      e.textContent = msg;
      e.hidden = false;
    },
    hide(msg) {
      const e = el();
      if (e && e.textContent === msg) e.hidden = true;
    },
  };
}

/** Tryb zastępczy, gdy nie ma WebGL2 albo GPU ma za małe tekstury: tylko komunikat. */
function errorMode(root, message) {
  root.innerHTML = '';
  const err = pageError();
  return {
    activate() { err.show(message); },
    deactivate() { err.hide(message); },
  };
}

export function createSurfaceMode({ root, api, endpoint, clock }) {
  root.innerHTML = '';
  const canvas = document.createElement('canvas');
  canvas.className = 'surface-gl';
  // geografia.py:2550-2558: kontekst GL 3.3 core bez atrybutów multisample → antialias: false
  const gl = canvas.getContext('webgl2', { depth: true, alpha: false, antialias: false });
  if (!gl) return errorMode(root, MSG_NO_WEBGL2);
  const maxTex = gl.getParameter(gl.MAX_TEXTURE_SIZE);
  if (!(maxTex >= MIN_TEXTURE_SIZE)) {
    return errorMode(root, `This GPU supports textures up to ${maxTex} px; the terrain needs ${MIN_TEXTURE_SIZE} px.`);
  }
  const overlay = document.createElement('canvas');
  overlay.className = 'surface-overlay';
  const ctx2d = overlay.getContext('2d');
  root.append(canvas, overlay);

  const err = pageError();
  let active = false;
  let fatalMsg = '';
  let contextLost = false;
  const fatal = (msg) => {
    fatalMsg = msg;
    if (active) err.show(msg);
  };
  canvas.addEventListener('webglcontextlost', () => {
    contextLost = true;
    fatal(MSG_CONTEXT_LOST);
  });

  // --- stan (geografia.py:2565-2584) ---
  let camAz = 15.0 * DEG;
  let camAlt = 14.0 * DEG;
  let fov = BASE_FOV;
  let targetFov = BASE_FOV;
  let wireframe = false;
  let showHorizonLine = true;
  let locationName = 'Tycho Crater';
  let pendingPreset = null;   // azymut presetu: kamera ustawiana po odpowiedzi observer (M4)
  let statusMsg = '';
  let statusTimer = 0;
  let animTime = 0;
  let animFrozen = false;     // tylko debug: stały czas animacji chmur

  // --- suwaki (geografia.py:2591-2595): obserwator w lewym górnym rogu, czas na dole ---
  const panel = document.createElement('div');
  panel.className = 'sim-panel surface-observer';
  const timePanel = document.createElement('div');
  timePanel.className = 'sim-panel surface-time';
  root.append(panel, timePanel);
  const deg2 = (v) => `${signed(v, 2)}°`;   // "{:+.2f}°"
  const sLat = makeSlider(panel, { label: 'Latitude (Lat)', min: -90.0, max: 90.0, value: -43.31, format: deg2 });
  const sLon = makeSlider(panel, { label: 'Longitude (Lon)', min: -180.0, max: 180.0, value: -11.36, format: deg2 });
  const sHeight = makeSlider(panel, {
    label: 'Height Above Surface', min: 2.0, max: 50000.0, value: 15.0, power: 3.0, format: formatHeightM,
  });
  const sYear = makeSlider(timePanel, { label: 'Year', min: 2000, max: 2100, value: 2000, isInt: true });
  const sTime = makeSlider(timePanel, {
    label: 'Time of Year', min: 0, max: 1, value: 0, format: (idx) => fmtUtc(yearStartMs(sYear.value) + idx * HOUR_MS),
  });

  // geografia.py:2703-2705: ruch lat/lon → "Custom Coordinates"
  sLat.onInput = sLon.onInput = () => {
    locationName = 'Custom Coordinates';
    pendingPreset = null;
    observerChanged();
  };
  sHeight.onInput = () => observerChanged();

  const syncTimeSliders = () => {
    const { year, idx } = timeParts(clock.t);
    sYear.set(year);
    sTime.max = Math.max(0, yearRows(year) - 1);
    sTime.set(Math.min(idx, sTime.max), fmtUtc(clock.t));
  };
  // geografia.py:2699-2700, 2773-2776: nowy rok, indeks przycięty do jego zakresu
  sYear.onInput = (year) => {
    const idx = Math.min(timeParts(clock.t).idx, Math.max(0, yearRows(year) - 1));
    clock.seek(yearStartMs(year) + idx * HOUR_MS);
  };
  sTime.onInput = (idx) => clock.seek(yearStartMs(sYear.value) + idx * HOUR_MS);

  const observer = () => ({ lat_deg: sLat.value, lon_deg: sLon.value, eye_height_m: sHeight.value });
  const obsKey = () => `${sLat.value}|${sLon.value}|${sHeight.value}`;

  // --- teren: katalog → obserwator → okna kafli → renderer ---
  let catalog = null;
  let renderer = null;
  let demWin = null;
  let albWin = null;
  let obsTimer = 0;
  let obsAbort = null;
  let obsSeq = 1;        // generacja obserwatora: rośnie przy każdej zmianie suwaków/presetu
  let tilesSeq = 0;      // generacja, dla której przyszła odpowiedź observer (składamy okna)
  let drawSeq = 0;       // generacja ustawiona w rendererze (okna gotowe)
  let terrainKey = '';   // obserwator terenu (obsKey w chwili żądania)
  let lastGeom = null;   // ostatnia odpowiedź observer dla bieżącego obserwatora (CSV)
  let obsChangedAt = 0;
  let firstObserver = true;

  function setStatus(msg) {
    statusMsg = msg;
    statusTimer = 3.5;
  }

  function observerChanged() {
    obsSeq++;
    obsChangedAt = performance.now();
    clearTimeout(obsTimer);
    obsTimer = setTimeout(loadObserver, OBSERVER_DEBOUNCE_MS);
  }

  async function loadObserver() {
    if (!renderer) return;   // katalog jeszcze nie przyszedł — wywoła nas jego .then
    clearTimeout(obsTimer);
    obsAbort?.abort();
    const ctrl = new AbortController();
    obsAbort = ctrl;
    const seq = obsSeq;
    const key = obsKey();
    try {
      const geom = await api.getJson(endpoint('lunar_surface.observer'), observer(), { signal: ctrl.signal });
      if (seq !== obsSeq) return;
      tilesSeq = seq;
      lastGeom = geom;
      const { lat_deg: lat, lon_deg: lon } = geom.observer;
      const ok = await Promise.all([
        demWin.ensure(lat, lon, geom.r_max_km, ctrl.signal),
        albWin.ensure(lat, lon, geom.r_max_km, ctrl.signal),
      ]);
      if (seq !== obsSeq || !ok[0] || !ok[1]) return;
      renderer.setObserver(geom);
      drawSeq = seq;
      terrainKey = key;
      if (firstObserver) {
        firstObserver = false;
        // geografia.py:2598-2600
        camAlt = Math.max(camAlt, renderer.horizonAt(camAz) + 6.0 * DEG);
      }
      if (pendingPreset) {
        // geografia.py:2764-2769 (preset czeka na swojego obserwatora, także po zastąpionym/nieudanym żądaniu)
        camAz = pendingPreset.azDeg * DEG;
        const horAlt = renderer.horizonAt(camAz);
        camAlt = Math.min(Math.PI / 2.0 - 0.05, horAlt + 5.5 * DEG);
        pendingPreset = null;
      }
    } catch (e) {
      if (e?.name === 'AbortError' || seq !== obsSeq) return;
      console.error(e);
      // błąd HTTP/sieci (obserwator albo kafel): komunikat i ponowienie, dopóki obserwator jest bieżący
      setStatus(`Terrain error: ${e?.message ?? e}. Retrying…`);
      clearTimeout(obsTimer);
      obsTimer = setTimeout(() => { if (seq === obsSeq) loadObserver(); }, RETRY_MS);
    } finally {
      if (obsAbort === ctrl) obsAbort = null;
    }
  }

  /** Teren rysujemy tylko dla bieżącej generacji obserwatora i z gotowymi oknami (M2). */
  const terrainReady = () => renderer !== null && drawSeq === obsSeq && demWin.ready && albWin.ready;

  api.getJson(endpoint('lunar_surface.catalog'), {}, { cache: true })
    .then((cat) => {
      catalog = cat;
      renderer = new TerrainRenderer(gl, cat);
      demWin = new TileWindow(gl, cat.dem, {
        internalFormat: gl.R32F, format: gl.RED, type: gl.FLOAT, mipmaps: false, unit: 0, rMoonKm: cat.r_moon_km,
      });
      albWin = new TileWindow(gl, cat.albedo, {
        internalFormat: gl.RGB8, format: gl.RGB, type: gl.UNSIGNED_BYTE, mipmaps: true, unit: 1, rMoonKm: cat.r_moon_km,
      });
      loadObserver();
    })
    .catch((e) => {
      console.error(e);
      fatal(`Couldn't load the terrain: ${e?.message ?? e}`);
    });

  // --- niebo GPU: gwiazdy (static) → SkyRenderer; tekstury Ziemi w tle ---
  let skyR = null;
  function loadStars() {
    api.getJson(endpoint('lunar_surface.stars'), {}, { cache: true })
      .then((stars) => {
        skyR = new SkyRenderer(gl, stars);
        skyR.loadEarthTextures().catch((e) => console.error(e));
      })
      .catch((e) => {
        console.error(e);
        setStatus(`Star catalog error: ${e?.message ?? e}. Retrying…`);
        setTimeout(loadStars, RETRY_MS);
      });
  }
  loadStars();

  // --- niebo: przeniesione z poprzedniego portu (jedno żądanie w locie, interpolacja) ---
  let skyPrev = null;
  let skyCurr = null;
  let skyAbort = null;
  let skyLastReq = 0;
  let skyReqKey = '';
  let skyObsKey = '';
  let skyInflightObs = null;

  /**
   * Niebo: jedno żądanie naraz. Zmiana czasu nie przerywa żądania w locie — po odpowiedzi
   * następna klatka pyta o bieżący czas. Przerywamy tylko przy zmianie obserwatora, a o nowego
   * obserwatora pytamy dopiero, gdy przestanie się zmieniać (jak debounce terenu).
   */
  function maybeFetchSky(now) {
    const reqObs = obsKey();
    if (skyAbort && skyInflightObs !== reqObs) { skyAbort.abort(); skyAbort = null; }
    if (skyAbort) return;
    if (now - obsChangedAt < OBSERVER_DEBOUNCE_MS) return;
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
      .catch((e) => {
        if (e?.name === 'AbortError') return;
        skyReqKey = '';   // 503 / błąd sieci: ponów po SKY_MIN_INTERVAL_MS
        if (e?.status !== 503) setStatus(`Sky error: ${e?.message ?? e}`);
      })
      .finally(() => { if (skyAbort === ctrl) skyAbort = null; });
  }

  // Obrót Ziemi między próbkami nieba: osie ECEF obracają się wokół osi Z z szybkością GMST
  // z get_topocentric_vectors (360.98564736629°/dobę) — tylko interpolacja do rysowania.
  const EARTH_RATE = (360.98564736629 * DEG) / 86_400_000;   // rad/ms
  const rotateAxes = (A, dtMs) => {
    const th = EARTH_RATE * dtMs;
    const c = Math.cos(th);
    const s = Math.sin(th);
    const [x, y, z] = A;
    return [x.map((v, i) => c * v + s * y[i]), y.map((v, i) => -s * x[i] + c * v), z];
  };
  // Gram-Schmidt bez iloczynu wektorowego: baza [N, E, U] jest lewoskrętna, więc Z × X po
  // składowych dałoby −Y. (Te same kroki co w poprzednim porcie, na tablicach.)
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const normalize3 = (a) => { const l = Math.sqrt(dot3(a, a)) || 1; return a.map((v) => v / l); };
  const addScaled3 = (a, b, s) => a.map((v, i) => v + b[i] * s);
  const orthonormal = ([x, y, z]) => {
    const Z = normalize3(z);
    let X = [...x];
    X = normalize3(addScaled3(X, Z, -dot3(X, Z)));
    let Y = [...y];
    Y = addScaled3(Y, Z, -dot3(Y, Z));
    Y = normalize3(addScaled3(Y, X, -dot3(Y, X)));
    return [X, Y, Z];
  };

  /**
   * Stan nieba w chwili clock.t: dokładna odpowiedź, gdy jej czas = clock.t (HUD = backend do
   * ostatniej cyfry); inaczej liniowa inter/ekstrapolacja między dwiema ostatnimi odpowiedziami.
   */
  function skyAt(tMs) {
    if (!skyCurr) return null;
    if (tMs === skyCurr._tMs) return { ...skyCurr, _f: 1, _base: skyCurr, _dtMs: 0 };
    if (!skyPrev || skyCurr._tMs === skyPrev._tMs) {
      return { ...skyCurr, earth_axes_enu: rotateAxes(skyCurr.earth_axes_enu, tMs - skyCurr._tMs), _f: 0, _base: skyCurr, _dtMs: tMs - skyCurr._tMs };
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

  // --- kamera ---
  // geografia.py:2623-2640
  function zoomAtPoint(zoomFactor, mx, my, cw, ch) {
    const oldTarget = targetFov;
    targetFov = Math.max(MIN_FOV, Math.min(MAX_FOV, targetFov * zoomFactor));
    if (Math.abs(targetFov - oldTarget) < 1e-9) return;
    const focalOld = (ch / 2.0) / Math.tan(oldTarget / 2.0);
    const focalNew = (ch / 2.0) / Math.tan(targetFov / 2.0);
    const dxPx = mx - cw / 2.0;
    const dyPx = ch / 2.0 - my;
    camAz = mod2pi(
      camAz
      + (Math.atan2(dxPx, focalOld) - Math.atan2(dxPx, focalNew)) / Math.max(0.25, Math.cos(camAlt)),
    );
    camAlt = Math.max(
      -Math.PI / 2.0 + 0.01,
      Math.min(Math.PI / 2.0 - 0.01, camAlt + (Math.atan2(dyPx, focalOld) - Math.atan2(dyPx, focalNew))),
    );
  }

  // geografia.py:2764-2769: preset ustawia lat/lon; kamera po odpowiedzi observer
  function applyPreset(code) {
    const p = PRESETS[code];
    if (!p) return;
    const [name, lat, lon, azDeg] = p;
    locationName = name;
    sLat.set(lat);
    sLon.set(lon);
    pendingPreset = { azDeg };
    observerChanged();
  }

  // geografia.py:2760-2763 (+ odchylenie 6: plik pobiera przeglądarka)
  function exportHorizonCsv() {
    const geom = lastGeom;
    if (!geom) return;
    const blob = new Blob([horizonCsv(geom)], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'horizon.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    setStatus('Saved horizon profile: horizon.csv');
  }

  // --- wejście: mysz (geografia.py:2709-2725) i klawiatura (:2726-2769) ---
  let dragging = false;
  let last = [0, 0];
  canvas.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    dragging = true;
    last = [ev.clientX, ev.clientY];
    canvas.setPointerCapture(ev.pointerId);
  });
  canvas.addEventListener('pointerup', (ev) => { if (ev.button === 0) dragging = false; });
  // przerwany wskaźnik (dotyk, gest systemu) też kończy przeciąganie — inaczej kamera „wisi”
  canvas.addEventListener('pointercancel', () => { dragging = false; });
  canvas.addEventListener('lostpointercapture', () => { dragging = false; });
  canvas.addEventListener('pointermove', (ev) => {
    if (!dragging) return;
    const dx = ev.clientX - last[0];
    const dy = ev.clientY - last[1];
    last = [ev.clientX, ev.clientY];
    const sens = fov / canvas.height;
    camAz = mod2pi(camAz - dx * sens);
    camAlt = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, camAlt + dy * sens));
  });
  canvas.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const steps = -Math.sign(ev.deltaY);   // event.y w pygame: +1 = kółko od siebie
    if (!steps) return;
    const r = canvas.getBoundingClientRect();
    zoomAtPoint(0.80 ** steps, ev.clientX - r.left, ev.clientY - r.top, canvas.width, canvas.height);
  }, { passive: false });

  /** Klawisz → akcja (null = nie nasz). pygame bez key.set_repeat: auto-powtórzenia ignorujemy (M5). */
  function keyAction(ev) {
    const k = ev.key.length === 1 ? ev.key.toLowerCase() : ev.key;
    const cw = canvas.width;
    const ch = canvas.height;
    if (ev.code === 'Space' || k === ' ') {
      return () => {
        // przycisk z fokusem (np. ▶ Play) dostałby jeszcze „klik” ze spacji przy keyup
        if (document.activeElement instanceof HTMLButtonElement) document.activeElement.blur();
        clock.toggle();
      };
    }
    if (k === '+' || k === '=' || ev.code === 'NumpadAdd') return () => zoomAtPoint(0.75, cw / 2.0, ch / 2.0, cw, ch);
    if (k === '-' || ev.code === 'NumpadSubtract') return () => zoomAtPoint(1.0 / 0.75, cw / 2.0, ch / 2.0, cw, ch);
    if (k === 'r') return () => { targetFov = BASE_FOV; };
    if (k === 'e' || k === 's') {
      // geografia.py:2735-2750: kamera na ciało; drugie naciśnięcie (< 2°) zoomuje
      return () => {
        const sky = skyAt(clock.t);
        if (!sky) return;
        const b = k === 'e' ? sky.earth : sky.sun;
        const bAlt = b.alt_deg * DEG;
        const bAz = b.az_deg * DEG;
        const distAng = Math.hypot(camAlt - bAlt, pyMod(camAz - bAz + Math.PI, 2 * Math.PI) - Math.PI);
        camAlt = bAlt;
        camAz = bAz;
        if (distAng < 2.0 * DEG) targetFov = (k === 'e' ? 3.2 : 1.4) * DEG;
      };
    }
    if (k === 'l') {
      // geografia.py:2751-2755
      return () => {
        if (!renderer) return;
        const horAlt = renderer.horizonAt(camAz);
        if (Math.abs(camAlt - horAlt) < 1.5 * DEG) targetFov = 8.0 * DEG;
        camAlt = horAlt;
      };
    }
    if (k === 'm') return () => { wireframe = !wireframe; };
    if (k === 'h') return () => { showHorizonLine = !showHorizonLine; };
    if (k === 'c') return exportHorizonCsv;
    if (PRESETS[ev.code]) return () => applyPreset(ev.code);
    return null;
  }

  function onKey(ev) {
    if (ev.target instanceof HTMLInputElement || ev.target instanceof HTMLSelectElement
      || ev.target instanceof HTMLTextAreaElement) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const action = keyAction(ev);
    if (!action) return;
    ev.preventDefault();
    if (ev.repeat) return;
    action();
  }

  const onTime = () => syncTimeSliders();

  // --- nakładka 2D: HUD geografii + stan ładowania (po polsku) ---
  function loadingLine(sky) {
    if (!renderer || tilesSeq === 0) return 'Loading observer…';
    if (drawSeq !== obsSeq) {
      if (tilesSeq !== obsSeq) return 'Loading observer…';
      const k = demWin.loaded + albWin.loaded;
      const n = demWin.total + albWin.total;
      return `Loading terrain tiles ${k}/${n}`;
    }
    if (!sky || skyObsKey !== terrainKey) return 'Loading sky…';
    return '';
  }

  let hudCache = [];
  function drawOverlay(view, sky, sunProj, earthProj, terrainOk) {
    ctx2d.clearRect(0, 0, overlay.width, overlay.height);
    if (sky) {
      // geografia.py:2909-2919
      if (sunProj) {
        const [sx, sy, zCam, focal] = sunProj;
        const rLabel = Math.max(6, Math.trunc(Math.tan(sky.sun.angular_radius_deg * DEG) * focal / zCam));
        if (sx + rLabel + 6 >= 0 && sx + rLabel + 6 < view.cw && sy - 8 >= 0 && sy - 8 < view.ch) {
          drawBodyLabel(ctx2d, 'Sun', sx + rLabel + 6, sy - 8, [255, 230, 150]);
        }
      }
      if (earthProj) {
        const [ex, ey, zCam, focal] = earthProj;
        const rLabel = Math.max(8, Math.trunc(Math.tan(sky.earth.angular_radius_deg * DEG) * focal / zCam));
        if (ex + rLabel + 8 >= 0 && ex + rLabel + 8 < view.cw && ey - 8 >= 0 && ey - 8 < view.ch) {
          drawBodyLabel(ctx2d, 'Earth', ex + rLabel + 8, ey - 8, [130, 200, 255]);
        }
      }
    }
    if (renderer?.horizonAlt) drawCompass(ctx2d, view, (az) => renderer.horizonAt(az));
    const status = statusTimer > 0 ? statusMsg : '';
    let hudShown = false;
    if (sky && renderer?.geom) {
      // geografia.py:2930-2950
      const drawnCount = terrainOk ? renderer.drawnCount : 0;
      hudCache = hudLines({
        locationName,
        demSource: catalog.dem_source,
        obsElevKm: renderer.obsElevKm,
        slopeDeg: renderer.obsSlopeDeg,
        slopeDir: renderer.obsSlopeDir,
        heightStr: formatHeightM(sHeight.value),
        zoomMag: BASE_FOV / fov,
        camAz,
        camAlt,
        camHor: renderer.horizonAt(camAz),
        drawnCount,
        nTris: drawnCount * (PATCH_N * PATCH_N * 2),
        lodTauUsed: renderer.lodTauUsed,
        earthAltDeg: sky.earth.alt_deg,
        earthAzDeg: sky.earth.az_deg,
        earthVis: sky._base.earth.status,
        sunAltDeg: sky.sun.alt_deg,
        sunAzDeg: sky.sun.az_deg,
        sunVis: sky._base.sun.status,
      });
      drawHud(ctx2d, hudCache, { panelW: 675, statusMsg: status });
      hudShown = true;
    }
    const lines = [loadingLine(sky), hudShown ? '' : status].filter(Boolean);
    if (lines.length) {
      ctx2d.font = HUD_FONT;
      ctx2d.textAlign = 'center';
      ctx2d.textBaseline = 'middle';
      lines.forEach((ln, i) => {
        ctx2d.fillStyle = i === 0 ? 'rgb(210, 215, 225)' : 'rgb(120, 235, 150)';
        ctx2d.fillText(ln, overlay.width / 2, overlay.height / 2 + i * 22);
      });
    }
  }

  // --- pętla ---
  let raf = 0;
  let lastFrame = 0;
  let fps = 0;
  let fpsFrames = 0;
  let fpsT0 = 0;

  function renderFrame(now) {
    const dt = lastFrame ? Math.min(0.1, (now - lastFrame) / 1000) : 0;
    lastFrame = now;
    fpsFrames++;
    if (!fpsT0) fpsT0 = now;
    if (now - fpsT0 >= 1000) {
      fps = (fpsFrames * 1000) / (now - fpsT0);
      fpsFrames = 0;
      fpsT0 = now;
    }
    if (!animFrozen) animTime += dt;   // geografia.py:2684
    if (statusTimer > 0) statusTimer = Math.max(0, statusTimer - dt);
    // geografia.py:2771
    fov += (targetFov - fov) * Math.min(1.0, 14.0 * dt);
    // geografia.py:2778-2781: +24 indeksy/s, po końcu roku powrót do 0 w tym samym roku
    if (clock.playing) {
      const { year, idx } = timeParts(clock.t);
      let next = idx + PLAY_SPEED * dt;
      if (next >= yearRows(year) - 1) next = 0;
      clock.seek(yearStartMs(year) + next * HOUR_MS);
    }

    maybeFetchSky(now);
    const sky = skyAt(clock.t);
    if (contextLost || gl.isContextLost()) return;

    const cw = canvas.width;
    const ch = canvas.height;
    gl.viewport(0, 0, cw, ch);
    // geografia.py:2839-2844
    gl.clearColor(5.0 / 255.0, 7.0 / 255.0, 12.0 / 255.0, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const view = cameraView(cw, ch, camAlt, camAz, fov);
    let sunProj = null;
    let earthProj = null;
    if (sky) {
      const sunAlt = sky.sun.alt_deg * DEG;
      const sunAz = sky.sun.az_deg * DEG;
      const earthAlt = sky.earth.alt_deg * DEG;
      const earthAz = sky.earth.az_deg * DEG;
      const angSun = sky.sun.angular_radius_deg * DEG;
      const angEarth = sky.earth.angular_radius_deg * DEG;
      sunProj = projectPoint(sunAlt, sunAz, view);
      earthProj = projectPoint(earthAlt, earthAz, view);
      if (skyR) {
        // geografia.py:2846-2850 — 1. gwiazdy, 2. siatka
        skyR.drawStars({ ...view, eclipticToEnu: sky.ecliptic_to_enu });
        skyR.drawGrid(view);
        // geografia.py:2852-2857 — 3. Słońce
        if (sunProj) {
          const [sx, sy, zCam, focal] = sunProj;
          skyR.drawTelescopicSun(view, { sx, sy, rExact: Math.tan(angSun) * focal / zCam });
        }
        // geografia.py:2859-2873 — 4. Ziemia (po wczytaniu tekstur: skrypt ma je przed pierwszą klatką)
        if (earthProj && skyR.texturesSettled) {
          const [ex, ey, zCam, focal] = earthProj;
          // cloud_offset = (d_rel·0.015 + anim_time·0.0012) % 1, d_rel = dni od początku roku
          const dRel = (clock.t - yearStartMs(timeParts(clock.t).year)) / 86_400_000;
          skyR.drawTelescopicEarth(view, {
            ex, ey, rExact: Math.tan(angEarth) * focal / zCam,
            dirEnu: sky.earth.dir_enu,
            cloudOffset: pyMod(dRel * 0.015 + animTime * 0.0012, 1.0),
          }, sky);
        }
      }
    }

    // geografia.py:2875-2883 — 5. teren (oświetlenie z nieba tego samego obserwatora, M2)
    const terrainOk = terrainReady() && sky !== null && skyObsKey === terrainKey;
    if (terrainOk) {
      renderer.draw({
        cw, ch, camAlt, camAz, fov,
        sunAlt: sky.sun.alt_deg * DEG,
        sunAz: sky.sun.az_deg * DEG,
        earthAlt: sky.earth.alt_deg * DEG,
        earthAz: sky.earth.az_deg * DEG,
        sunEffectiveVis: sky.sun.effective_visibility,
        eclipseRedGlow: sky.eclipse_red_glow,
        wireframe,
        showHorizonLine,
        demWin,
        albedoWin: albWin,
      });
    }
    // geografia.py:2885-2993 — 6. HUD
    drawOverlay(view, sky, sunProj, earthProj, terrainOk);
    return terrainOk;
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    renderFrame(now);
  }

  // Canvas w pikselach CSS (odchylenie 8: devicePixelRatio = 1)
  function resize() {
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    if (overlay.width !== w || overlay.height !== h) {
      overlay.width = w;
      overlay.height = h;
    }
  }
  const ro = new ResizeObserver(resize);

  syncTimeSliders();

  // Uchwyt do debugowania i weryfikacji w konsoli.
  root._debug = {
    gl,
    get renderer() { return renderer; },
    get skyRenderer() { return skyR; },
    get drawnCount() { return renderer?.drawnCount ?? 0; },
    get nTris() { return renderer?.nTris ?? 0; },
    get lodTauUsed() { return renderer?.lodTauUsed ?? TAU_PX; },
    get tiles() { return demWin && { dem: demWin.info(), albedo: albWin.info() }; },
    get fps() { return fps; },
    get observer() { return renderer?.geom ?? null; },
    get lastGeom() { return lastGeom; },
    get ready() { return terrainReady() && skyObsKey === terrainKey; },
    get locationName() { return locationName; },
    get camera() { return { camAlt, camAz, fov, targetFov, wireframe, showHorizonLine }; },
    get sky() { return skyAt(clock.t); },
    get hud() { return hudCache; },
    get status() { return statusTimer > 0 ? statusMsg : ''; },
    get sliders() {
      return Object.fromEntries([sLat, sLon, sHeight, sYear, sTime].map((s) => [s.label, s.el.textContent]));
    },
    get seq() { return { obsSeq, tilesSeq, drawSeq, terrainKey, skyObsKey }; },
    horizonCsv() { return lastGeom ? horizonCsv(lastGeom) : null; },
    setAnimTime(v) { animTime = v; animFrozen = true; },
    setCamera(altDeg, azDeg, fovDeg = BASE_FOV / DEG) {
      camAlt = altDeg * DEG; camAz = azDeg * DEG; fov = targetFov = fovDeg * DEG;
    },
    setCameraRad(alt, az, fovRad = BASE_FOV) {
      camAlt = alt; camAz = az; fov = targetFov = fovRad;
    },
    setLocation(lat, lon, eye = sHeight.value) {
      sLat.set(lat); sLon.set(lon); sHeight.set(eye);
      locationName = 'Custom Coordinates';
      pendingPreset = null;
      observerChanged();
    },
    get windows() { return { dem: demWin, albedo: albWin }; },
    /** Klatka narysowana od razu (poza rAF) i odczytana readPixels w tym samym zadaniu (RGBA, wiersz 0 = dół). */
    readFrame() {
      const terrainDrawn = renderFrame(performance.now());
      const w = gl.canvas.width;
      const h = gl.canvas.height;
      const px = new Uint8Array(w * h * 4);
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
      return { w, h, px, terrainDrawn };
    },
    /**
     * Czas klatki niezależny od rAF (przeglądarki potrafią dławić rAF w tle): `iters` klatek
     * terenu rysowanych od razu, każda zakończona readPixels (synchronizacja z GPU).
     */
    benchmark(iters = 20) {
      const sky = skyAt(clock.t);
      if (!terrainReady() || !sky) return null;
      const cw = canvas.width;
      const ch = canvas.height;
      const px = new Uint8Array(4);
      const times = [];
      for (let i = 0; i < iters; i++) {
        const t0 = performance.now();
        gl.viewport(0, 0, cw, ch);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        renderer.draw({
          cw, ch, camAlt, camAz, fov,
          sunAlt: sky.sun.alt_deg * DEG, sunAz: sky.sun.az_deg * DEG,
          earthAlt: sky.earth.alt_deg * DEG, earthAz: sky.earth.az_deg * DEG,
          sunEffectiveVis: sky.sun.effective_visibility, eclipseRedGlow: sky.eclipse_red_glow,
          wireframe, showHorizonLine, demWin, albedoWin: albWin,
        });
        gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
        times.push(performance.now() - t0);
      }
      times.sort((a, b) => a - b);
      const median = times[times.length >> 1];
      return { medianMs: median, fps: 1000 / median, drawnCount: renderer.drawnCount, lodTauUsed: renderer.lodTauUsed, cw, ch };
    },
    /** _select_lod na świeżym stanie (lodTau = TAU_PX) dla porównania z Pythonem; stan rendera bez zmian. */
    lodParity(cw, ch, camAltRad, camAzRad, fovRad) {
      const saved = [renderer.lodTau, renderer.lodTauUsed, renderer.quadCount];
      renderer.lodTau = TAU_PX;
      const p = renderer.selectLod(cw, ch, camAltRad, camAzRad, fovRad);
      const out = { n: p.lat0.length, lodTauUsed: renderer.lodTauUsed, lodTau: renderer.lodTau };
      [renderer.lodTau, renderer.lodTauUsed, renderer.quadCount] = saved;
      return out;
    },
  };

  return {
    activate() {
      active = true;
      if (fatalMsg) err.show(fatalMsg);
      ro.observe(canvas);
      resize();
      window.addEventListener('keydown', onKey);
      clock.addEventListener('timechange', onTime);
      syncTimeSliders();
      lastFrame = 0;
      fpsT0 = 0;
      fpsFrames = 0;
      skyReqKey = '';
      raf = requestAnimationFrame(frame);
    },
    deactivate() {
      active = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener('keydown', onKey);
      clock.removeEventListener('timechange', onTime);
      skyAbort?.abort();
      if (fatalMsg) err.hide(fatalMsg);
    },
  };
}
