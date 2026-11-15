// HUD trybu Powierzchnia: panel informacyjny, etykiety „Sun”/„Earth” i kompas z geografia.main()
// (geografia.py:2909-2981) rysowane na canvasie 2D nad WebGL (odchylenie 5: bez tekstury HUD),
// plus eksport profilu horyzontu do CSV (export_horizon_csv, geografia.py:1961-1994).
// Liczby formatujemy jak Python (pyFixed: zaokrąglanie do parzystej przy dokładnym remisie, „-0.00”),
// żeby HUD i CSV zgadzały się ze skryptem do ostatniej cyfry.

export const HUD_FONT = '15px Consolas, "DejaVu Sans Mono", monospace';            // SysFont("Consolas", 15)
export const HUD_FONT_BIG = 'bold 18px Consolas, "DejaVu Sans Mono", monospace';   // SysFont("Consolas", 18, bold=True)
export const RAD2DEG = 180.0 / Math.PI;   // math.degrees(x) = x · (180/π)

const rgb = ([r, g, b]) => `rgb(${r}, ${g}, ${b})`;

/** Wykładnik E dla x = M · 2^E z nieparzystym M (x > 0, skończone). */
function oddExponent(x) {
  const dv = new DataView(new ArrayBuffer(8));
  dv.setFloat64(0, x);
  const hi = dv.getUint32(0);
  const lo = dv.getUint32(4);
  const bexp = (hi >>> 20) & 0x7ff;
  let m = (hi & 0xfffff) * 2 ** 32 + lo;
  let e;
  if (bexp === 0) {
    e = -1074;
  } else {
    m += 2 ** 52;
    e = bexp - 1075;
  }
  while (m % 2 === 0) {
    m /= 2;
    e += 1;
  }
  return e;
}

/**
 * format(x, f'.{d}f') z Pythona. toFixed liczy na dokładnej wartości binarnej jak Python, różni się
 * tylko przy dokładnym remisie (Python: do parzystej, JS: w górę) i znakiem dla -0.0.
 * Remis na d miejscach ⇔ x = M·2^E z nieparzystym M i E = −(d+1).
 */
export function pyFixed(x, d) {
  if (Number.isNaN(x)) return 'nan';
  if (!Number.isFinite(x)) return x > 0 ? 'inf' : '-inf';
  const neg = x < 0 || Object.is(x, -0);
  const a = Math.abs(x);
  let s = a.toFixed(d);
  if (a !== 0 && oddExponent(a) === -(d + 1)) {
    let n = BigInt(s.replace('.', ''));
    if (n % 2n === 1n) {
      n -= 1n;
      const digits = n.toString().padStart(d + 1, '0');
      s = d > 0 ? `${digits.slice(0, -d)}.${digits.slice(-d)}` : digits;
    }
  }
  return (neg ? '-' : '') + s;
}

/** format(x, f'{sign}{width}.{d}f'), sign = '+' albo ''. */
export function pyFmt(x, d, sign = '', width = 0) {
  let s = pyFixed(x, d);
  if (sign === '+' && !s.startsWith('-')) s = `+${s}`;
  return s.padStart(width);
}

/** f'{n:,}' dla liczby całkowitej. */
export const thousands = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

// geografia.py:2642-2654 (get_camera_basis) + ogniskowa z project_point
/** Kamera klatki: baza [North, East, Up] i ogniskowa w pikselach. */
export function cameraView(cw, ch, camAlt, camAz, fov) {
  return {
    cw,
    ch,
    fov,
    camAlt,
    camAz,
    focal: (ch / 2.0) / Math.tan(fov / 2.0),
    fwd: [Math.cos(camAlt) * Math.cos(camAz), Math.cos(camAlt) * Math.sin(camAz), Math.sin(camAlt)],
    right: [-Math.sin(camAz), Math.cos(camAz), 0.0],
    camUp: [-Math.sin(camAlt) * Math.cos(camAz), -Math.sin(camAlt) * Math.sin(camAz), Math.cos(camAlt)],
  };
}

// geografia.py:2656-2671
/** project_point: [sx, sy, z_cam, focal] albo null, gdy punkt jest za kamerą (z_cam ≤ 0.05). */
export function projectPoint(alt, az, view) {
  const px = Math.cos(alt) * Math.cos(az);
  const py = Math.cos(alt) * Math.sin(az);
  const pz = Math.sin(alt);
  const { fwd, right, camUp, cw, ch, focal } = view;
  const zCam = px * fwd[0] + py * fwd[1] + pz * fwd[2];
  if (zCam <= 0.05) return null;
  const xCam = px * right[0] + py * right[1] + pz * right[2];
  const yCam = px * camUp[0] + py * camUp[1] + pz * camUp[2];
  return [cw / 2.0 + (xCam / zCam) * focal, ch / 2.0 - (yCam / zCam) * focal, zCam, focal];
}

// geografia.py:2930-2965 (tekst linii; liczby jak f-stringi w skrypcie)
/**
 * Linie panelu HUD.
 * @param {object} s stan: locationName, demSource, obsElevKm, slopeDeg, slopeDir, heightStr, zoomMag,
 *   camAz, camAlt, camHor [rad], drawnCount, nTris, lodTauUsed, earthAltDeg, earthAzDeg, earthVis,
 *   sunAltDeg, sunAzDeg, sunVis
 */
export function hudLines(s) {
  // geografia.py:2933-2937
  const slopeStr = s.slopeDir === 'Flat'
    ? `${pyFixed(s.slopeDeg, 2)}° (Flat)`
    : `${pyFixed(s.slopeDeg, 2)}° (${s.slopeDir})`;
  return [
    `Location: ${s.locationName} | DEM: ${s.demSource} (GPU PQS)`,
    `Terrain: ${pyFmt(s.obsElevKm, 3, '+')} km | Slope: ${slopeStr} | Alt: ${s.heightStr} | Zoom: ${pyFixed(s.zoomMag, 1)}x`,
    `Camera: Az ${pyFixed(s.camAz * RAD2DEG, 2)}° | Alt ${pyFmt(s.camAlt * RAD2DEG, 2, '+')}° (Hor: ${pyFmt(s.camHor * RAD2DEG, 2, '+')}°)`,
    `GPU Mesh: ${s.drawnCount} patches (${thousands(s.nTris)} triangles) | τ ${pyFixed(s.lodTauUsed, 1)} px`,
    '-'.repeat(66),
    `EARTH: Alt ${pyFmt(s.earthAltDeg, 2, '+', 6)}° | Az ${pyFmt(s.earthAzDeg, 2, '', 6)}° [${s.earthVis}]`,
    `SUN:   Alt ${pyFmt(s.sunAltDeg, 2, '+', 6)}° | Az ${pyFmt(s.sunAzDeg, 2, '', 6)}° [${s.sunVis}]`,
    '-'.repeat(66),
    '[Scroll / +/-] Zoom (up to 375x) | [R] Reset Zoom | [Space] Play/Pause',
    '[E] Earth (2x = zoom) | [S] Sun (2x = zoom) | [L] Level to Horizon',
    '[M] 3D Wireframe | [H] Horizon Line | [C] Export horizon.csv',
    '[1] Tycho [2] Copernicus [3] Shackleton (Crater)',
    '[4] Vallis Alpes (Alpine Valley) [5] Apollo 11',
  ];
}

// geografia.py:2967-2981
/** Panel HUD w prawym górnym rogu; statusMsg (pusty = brak) w dodatkowym wierszu na zielono. */
export function drawHud(ctx, lines, { panelW = 675, statusMsg = '' } = {}) {
  const cw = ctx.canvas.width;
  const extraH = statusMsg ? 24 : 0;
  ctx.fillStyle = `rgba(15, 20, 30, ${195 / 255})`;
  ctx.fillRect(cw - panelW - 15, 15, panelW, lines.length * 20 + 16 + extraH);
  ctx.font = HUD_FONT;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillStyle = rgb([210, 215, 225]);
  lines.forEach((line, i) => ctx.fillText(line, cw - panelW - 5, 22 + i * 20));
  if (statusMsg) {
    ctx.fillStyle = rgb([120, 235, 150]);
    ctx.fillText(statusMsg, cw - panelW - 5, 22 + lines.length * 20 + 4);
  }
}

// geografia.py:2909-2919 (blit tekstu lewym górnym rogiem w (x, y))
export function drawBodyLabel(ctx, text, x, y, color) {
  ctx.font = HUD_FONT;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillStyle = rgb(color);
  ctx.fillText(text, Math.trunc(x), Math.trunc(y));
}

const COMPASS = [['N', 0], ['NE', 45], ['E', 90], ['SE', 135], ['S', 180], ['SW', 225], ['W', 270], ['NW', 315]];

// geografia.py:2921-2928
/** Róża kierunków nad lokalnym horyzontem: alt = horyzont + max(1.2°, 0.02·fov). */
export function drawCompass(ctx, view, horizonAt) {
  ctx.font = HUD_FONT_BIG;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  for (const [label, deg] of COMPASS) {
    const azR = deg * (Math.PI / 180);   // math.radians
    const hAlt = horizonAt(azR) + Math.max(1.2 * (Math.PI / 180), view.fov * 0.02);
    const proj = projectPoint(hAlt, azR, view);
    if (proj && proj[0] >= 0 && proj[0] < view.cw && proj[1] >= 0 && proj[1] < view.ch) {
      const m = ctx.measureText(label);
      const w = Math.round(m.width);
      const h = Math.round(m.fontBoundingBoxAscent + m.fontBoundingBoxDescent);
      ctx.fillStyle = rgb(label === 'N' ? [255, 90, 90] : [210, 220, 235]);
      ctx.fillText(label, Math.trunc(proj[0] - Math.floor(w / 2)), Math.trunc(proj[1] - Math.floor(h / 2)));
    }
  }
}

const CSV_HEAD = [
  'Azimuth_deg', 'Horizon_Altitude_deg', 'Horizon_Distance_km', 'Horizon_Lat_deg', 'Horizon_Lon_deg',
  'Horizon_Elevation_km', 'Observer_Lat_deg', 'Observer_Lon_deg', 'Observer_Elevation_km',
  'Observer_Slope_deg', 'Observer_Downhill_Dir', 'Observer_Height_above_surface_m',
];
// csv.writer (QUOTE_MINIMAL, lineterminator "\r\n")
const csvField = (v) => (/[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

// geografia.py:1961-1994
/** horizon.csv z odpowiedzi lunar_surface.observer: nagłówek + n_az = 720 wierszy. */
export function horizonCsv(geom) {
  const h = geom.horizon;
  const nAz = h.az_deg.length - 1;   // az_grid ma 721 punktów, n_az = 720
  const rows = [CSV_HEAD];
  for (let idx = 0; idx < nAz; idx++) {
    rows.push([
      pyFixed(h.az_deg[idx], 4),
      pyFixed(h.alt_deg[idx], 6),
      pyFixed(h.distance_km[idx], 4),
      pyFixed(h.lat_deg[idx], 6),
      pyFixed(h.lon_deg[idx], 6),
      pyFixed(h.elevation_km[idx], 5),
      pyFixed(geom.observer.lat_deg, 6),
      pyFixed(geom.observer.lon_deg, 6),
      pyFixed(geom.observer_elevation_km, 5),
      pyFixed(geom.slope_deg, 3),
      geom.slope_dir,
      pyFixed(geom.eye_height_m, 2),
    ]);
  }
  return rows.map((r) => r.map(csvField).join(',')).join('\r\n') + '\r\n';
}
