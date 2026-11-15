// Tryb „Powierzchnia” — port geografia.py (silnik PQS na GPU) w surowym WebGL2, bez bibliotek 3D.
// Serwer liczy obserwatora (lunar_surface.observer: grunt, nachylenie, horyzont), niebo
// (lunar_surface.sky) i wydaje kafle DEM/albedo; teren składa i cieniuje GPU przeglądarki.
// Kamera, zoom, presety, suwaki lat/lon/wysokość i klawisze +/-/R/M/H/1-5 jak geografia.main()
// (geografia.py:2549-2770). Niebo, HUD, czas i pozostałe klawisze dochodzą w Tasku 4.

import { makeSlider } from '../ui/slider.js';
import { TerrainRenderer, TAU_PX } from './terrain-renderer.js';
import { TileWindow } from './tile-window.js';

const DEG = Math.PI / 180;
const TWO_PI = 2 * Math.PI;
// geografia.py:2570-2576
const BASE_FOV = 75.0 * DEG;           // pionowe pole widzenia (focal = (ch/2)/tan(fov/2))
const MIN_FOV = 0.20 * DEG;
const MAX_FOV = 115.0 * DEG;
const SKY_MIN_INTERVAL_MS = 200;
const OBSERVER_DEBOUNCE_MS = 250;
const MIN_TEXTURE_SIZE = 8192;         // albedo z pełnym pierścieniem: 32 × 256 px

const MSG_NO_WEBGL2 = 'Tryb Powierzchnia wymaga WebGL2 — ta przeglądarka go nie obsługuje.';
const MSG_CONTEXT_LOST = 'Utracono kontekst WebGL — odśwież stronę.';

// geografia.py:2673-2679 — (Name, Lat_deg, Lon_deg, Initial_Azimuth_deg)
const PRESETS = {
  1: ['Tycho Crater', -43.31, -11.36, 15.0],
  2: ['Copernicus Crater', 9.62, -20.08, 35.0],
  3: ['Shackleton (Crater)', -89.48, 129.80, 0.0],
  4: ['Vallis Alpes (Alpine Valley)', 48.65, 3.50, 56.0],
  5: ['Apollo 11 (Mare Tranquillitatis)', 0.67, 23.47, 270.0],
};

const fixed = (v, d) => (Object.is(v, -0) ? 0 : v).toFixed(d);
const signed = (v, d) => (v >= 0 ? '+' : '') + fixed(v, d);
const mod2pi = (a) => ((a % TWO_PI) + TWO_PI) % TWO_PI;

// geografia.py:2543-2546
/** geografia.format_height_m */
export function formatHeightM(m) {
  return m < 1000 ? `${m.toFixed(1)} m` : `${(m / 1000).toFixed(2)} km`;
}

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
    return errorMode(root, `GPU obsługuje tekstury do ${maxTex} px, teren wymaga ${MIN_TEXTURE_SIZE} px.`);
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

  // --- stan (geografia.py:2565-2576, 2596) ---
  let camAz = 15.0 * DEG;
  let camAlt = 14.0 * DEG;
  let fov = BASE_FOV;
  let targetFov = BASE_FOV;
  let wireframe = false;
  let showHorizonLine = true;
  let locationName = 'Tycho Crater';
  let pendingPreset = null;   // azymut presetu do ustawienia po odpowiedzi observer
  let statusMsg = '';
  let statusTimer = 0;

  // --- suwaki obserwatora (geografia.py:2593-2595; Year / Time of Year dochodzą w Tasku 4) ---
  const panel = document.createElement('div');
  panel.className = 'sim-panel surface-observer';
  root.append(panel);
  const deg2 = (v) => `${signed(v, 2)}°`;   // "{:+.2f}°"
  const sLat = makeSlider(panel, { label: 'Latitude (Lat)', min: -90.0, max: 90.0, value: -43.31, format: deg2 });
  const sLon = makeSlider(panel, { label: 'Longitude (Lon)', min: -180.0, max: 180.0, value: -11.36, format: deg2 });
  const sHeight = makeSlider(panel, {
    label: 'Height Above Surface', min: 2.0, max: 50000.0, value: 15.0, power: 3.0, format: formatHeightM,
  });
  // geografia.py:2703-2705: ruch lat/lon → "Custom Coordinates"
  sLat.onInput = sLon.onInput = () => {
    locationName = 'Custom Coordinates';
    pendingPreset = null;
    observerChanged();
  };
  sHeight.onInput = () => observerChanged();

  const observer = () => ({ lat_deg: sLat.value, lon_deg: sLon.value, eye_height_m: sHeight.value });
  const obsKey = () => `${sLat.value}|${sLon.value}|${sHeight.value}`;

  // --- teren: katalog → obserwator → okna kafli → renderer ---
  let renderer = null;
  let demWin = null;
  let albWin = null;
  let obsTimer = 0;
  let obsAbort = null;
  let obsGen = 0;       // ostatnie wysłane żądanie obserwatora
  let pendingGen = 0;   // generacja, dla której składamy okna (odpowiedź już jest)
  let drawGen = 0;      // generacja ustawiona w rendererze (okna gotowe)
  let obsChangedAt = 0;
  let firstObserver = true;

  function setStatus(msg) {
    statusMsg = msg;
    statusTimer = 3.5;
  }

  function observerChanged() {
    obsChangedAt = performance.now();
    clearTimeout(obsTimer);
    obsTimer = setTimeout(loadObserver, OBSERVER_DEBOUNCE_MS);
  }

  async function loadObserver() {
    if (!renderer) return;   // katalog jeszcze nie przyszedł — wywoła nas jego .then
    obsAbort?.abort();
    const ctrl = new AbortController();
    obsAbort = ctrl;
    const gen = ++obsGen;
    const preset = pendingPreset;
    pendingPreset = null;
    try {
      const geom = await api.getJson(endpoint('lunar_surface.observer'), observer(), { signal: ctrl.signal });
      if (gen !== obsGen) return;
      pendingGen = gen;
      const { lat_deg: lat, lon_deg: lon } = geom.observer;
      const ok = await Promise.all([
        demWin.ensure(lat, lon, geom.r_max_km, ctrl.signal),
        albWin.ensure(lat, lon, geom.r_max_km, ctrl.signal),
      ]);
      if (gen !== obsGen || !ok[0] || !ok[1]) return;
      renderer.setObserver(geom);
      drawGen = gen;
      if (firstObserver) {
        firstObserver = false;
        // geografia.py:2598-2600
        camAlt = Math.max(camAlt, renderer.horizonAt(camAz) + 6.0 * DEG);
      }
      if (preset) {
        // geografia.py:2766-2769
        camAz = preset.azDeg * DEG;
        const horAlt = renderer.horizonAt(camAz);
        camAlt = Math.min(Math.PI / 2.0 - 0.05, horAlt + 5.5 * DEG);
      }
    } catch (e) {
      if (e?.name === 'AbortError' || gen !== obsGen) return;
      console.error(e);
      setStatus(`Błąd terenu: ${e?.message ?? e}`);
    } finally {
      if (obsAbort === ctrl) obsAbort = null;
    }
  }

  const drawable = () => renderer !== null && drawGen !== 0 && pendingGen === drawGen && demWin.ready && albWin.ready;

  api.getJson(endpoint('lunar_surface.catalog'), {}, { cache: true })
    .then((cat) => {
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
      fatal(`Nie udało się przygotować terenu: ${e?.message ?? e}`);
    });

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
        if (e?.status !== 503) setStatus(`Błąd nieba: ${e?.message ?? e}`);
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
  // składowych dałoby −Y. (Te same kroki co wcześniej na THREE.Vector3, na tablicach.)
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
  function applyPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    const [name, lat, lon, azDeg] = p;
    locationName = name;
    sLat.set(lat);
    sLon.set(lon);
    pendingPreset = { azDeg };
    observerChanged();
  }

  // --- wejście: mysz (geografia.py:2709-2725) i klawiatura (:2726-2769, część Tasku 3) ---
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

  function onKey(ev) {
    if (ev.target instanceof HTMLInputElement || ev.target instanceof HTMLSelectElement) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const k = ev.key;
    const cw = canvas.width;
    const ch = canvas.height;
    if (k === '+' || k === '=' || ev.code === 'NumpadAdd') {
      zoomAtPoint(0.75, cw / 2.0, ch / 2.0, cw, ch);
    } else if (k === '-' || ev.code === 'NumpadSubtract') {
      zoomAtPoint(1.0 / 0.75, cw / 2.0, ch / 2.0, cw, ch);
    } else if (k === 'r' || k === 'R') {
      targetFov = BASE_FOV;
    } else if (k === 'm' || k === 'M') {
      wireframe = !wireframe;
    } else if (k === 'h' || k === 'H') {
      showHorizonLine = !showHorizonLine;
    } else if (PRESETS[k]) {
      applyPreset(k);
    } else {
      return;
    }
    ev.preventDefault();
  }

  // --- nakładka 2D: stan ładowania i komunikaty (HUD geografii dochodzi w Tasku 4) ---
  let overlayText = null;
  function drawOverlay(lines) {
    const text = lines.join('\n');
    if (text === overlayText) return;
    overlayText = text;
    ctx2d.clearRect(0, 0, overlay.width, overlay.height);
    ctx2d.font = '15px Consolas, "DejaVu Sans Mono", monospace';
    ctx2d.textAlign = 'center';
    ctx2d.textBaseline = 'middle';
    lines.forEach((ln, i) => {
      ctx2d.fillStyle = i === 0 ? 'rgb(210, 215, 225)' : 'rgb(120, 235, 150)';
      ctx2d.fillText(ln, overlay.width / 2, overlay.height / 2 + i * 22);
    });
  }

  function loadingLine(view) {
    if (!renderer || (drawGen === 0 && pendingGen === 0)) return 'Ładowanie obserwatora…';
    if (!drawable()) {
      const k = demWin.loaded + albWin.loaded;
      const n = demWin.total + albWin.total;
      return `Ładowanie kafli terenu ${k}/${n}`;
    }
    if (!view) return 'Ładowanie nieba…';
    return '';
  }

  // --- pętla ---
  let raf = 0;
  let lastFrame = 0;
  let fps = 0;
  let fpsFrames = 0;
  let fpsT0 = 0;
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = lastFrame ? Math.min(0.1, (now - lastFrame) / 1000) : 0;
    lastFrame = now;
    fpsFrames++;
    if (!fpsT0) fpsT0 = now;
    if (now - fpsT0 >= 1000) {
      fps = (fpsFrames * 1000) / (now - fpsT0);
      fpsFrames = 0;
      fpsT0 = now;
    }
    if (statusTimer > 0) statusTimer = Math.max(0, statusTimer - dt);
    // geografia.py:2771
    fov += (targetFov - fov) * Math.min(1.0, 14.0 * dt);

    maybeFetchSky(now);
    const view = skyAt(clock.t);
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
    // (geografia.py:2846-2873 — gwiazdy, siatka, Słońce, Ziemia: Task 4)

    // geografia.py:2875-2883
    if (drawable() && view) {
      renderer.draw({
        cw, ch, camAlt, camAz, fov,
        sunAlt: view.sun.alt_deg * DEG,
        sunAz: view.sun.az_deg * DEG,
        earthAlt: view.earth.alt_deg * DEG,
        earthAz: view.earth.az_deg * DEG,
        sunEffectiveVis: view.sun.effective_visibility,
        eclipseRedGlow: view.eclipse_red_glow,
        wireframe,
        showHorizonLine,
        demWin,
        albedoWin: albWin,
      });
    }
    drawOverlay([loadingLine(view), statusTimer > 0 ? statusMsg : ''].filter(Boolean));
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
      overlayText = null;
    }
  }
  const ro = new ResizeObserver(resize);

  // Uchwyt do debugowania i weryfikacji w konsoli.
  root._debug = {
    gl,
    get renderer() { return renderer; },
    get drawnCount() { return renderer?.drawnCount ?? 0; },
    get nTris() { return renderer?.nTris ?? 0; },
    get lodTauUsed() { return renderer?.lodTauUsed ?? TAU_PX; },
    get tiles() { return demWin && { dem: demWin.info(), albedo: albWin.info() }; },
    get fps() { return fps; },
    get observer() { return renderer?.geom ?? null; },
    get ready() { return drawable(); },
    get locationName() { return locationName; },
    get camera() { return { camAlt, camAz, fov, targetFov, wireframe, showHorizonLine }; },
    get sky() { return skyAt(clock.t); },
    setCamera(altDeg, azDeg, fovDeg = BASE_FOV / DEG) {
      camAlt = altDeg * DEG; camAz = azDeg * DEG; fov = targetFov = fovDeg * DEG;
    },
    setCameraRad(alt, az, fovRad = BASE_FOV) {
      camAlt = alt; camAz = az; fov = targetFov = fovRad;
    },
    setLocation(lat, lon, eye = sHeight.value) {
      sLat.set(lat); sLon.set(lon); sHeight.set(eye);
      locationName = 'Custom Coordinates';
      observerChanged();
    },
    get windows() { return { dem: demWin, albedo: albWin }; },
    /**
     * Czas klatki niezależny od rAF (przeglądarki potrafią dławić rAF w tle): `iters` klatek
     * terenu rysowanych od razu, każda zakończona readPixels (synchronizacja z GPU).
     */
    benchmark(iters = 20) {
      const view = skyAt(clock.t);
      if (!drawable() || !view) return null;
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
          sunAlt: view.sun.alt_deg * DEG, sunAz: view.sun.az_deg * DEG,
          earthAlt: view.earth.alt_deg * DEG, earthAz: view.earth.az_deg * DEG,
          sunEffectiveVis: view.sun.effective_visibility, eclipseRedGlow: view.eclipse_red_glow,
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
      skyAbort?.abort();
      if (fatalMsg) err.hide(fatalMsg);
    },
  };
}
