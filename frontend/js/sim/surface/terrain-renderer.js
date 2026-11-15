// Strona GPU LunarTerrain3D z geografia.py (silnik PQS): statyczna paczka 64×64 ze spódnicami,
// quadtree LOD liczone co klatkę w JS (Float64 jak numpy) i draw_3d w WebGL2. Geometrię
// obserwatora (grunt, nachylenie, horyzont) liczy serwer (lunar_surface.observer).

import { createProgram } from './gl.js';
import { HORIZON_FS, HORIZON_VS, TERRAIN_FS, TERRAIN_VS } from './shaders.js';

// geografia.py:13
const R_MOON = 1737.4;
// geografia.py:1217-1221
export const PATCH_N = 64;
export const TAU_PX = 1.5;
export const MAX_PATCHES = 1024;
export const MIN_CELL_SCALE = 0.005;

const DEG = Math.PI / 180;   // math.radians(x) = x · (π/180)
const TWO_PI = 2.0 * Math.PI;

/** np.linspace(start, stop, num) z endpoint=True: i·step + start, ostatni element = stop. */
function linspace(start, stop, num) {
  const out = new Float64Array(num);
  const step = (stop - start) / (num - 1);
  for (let i = 0; i < num; i++) out[i] = i * step + start;
  out[num - 1] = stop;
  return out;
}

/** np.cross dla wektorów 3D. */
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const clip = (x, lo, hi) => Math.min(Math.max(x, lo), hi);

// geografia.py:1579-1623
/** Statyczna paczka PATCH_N × PATCH_N z pionowymi spódnicami: (u, v, is_skirt), trójkąty, druty. */
export function buildStaticPatchGeometry() {
  const N = PATCH_N;
  const stride = N + 1;
  const uLin = linspace(0.0, 1.0, N + 1);
  const vLin = uLin;
  const nCore = (N + 1) * (N + 1);
  const verts = new Float32Array((nCore + 4 * (N + 1)) * 3);
  for (let r = 0; r <= N; r++) {
    for (let c = 0; c <= N; c++) {
      const k = (r * stride + c) * 3;
      verts[k] = uLin[c];
      verts[k + 1] = vLin[r];
      verts[k + 2] = 0.0;
    }
  }
  const tris = new Uint32Array(N * N * 6 + 4 * N * 6);
  const wire = new Uint32Array(N * N * 4);
  let ti = 0;
  let wi = 0;
  for (let r = 0; r < N; r++) {
    for (let c = 0; c < N; c++) {
      const i00 = r * stride + c;
      const i10 = (r + 1) * stride + c;
      const i11 = (r + 1) * stride + (c + 1);
      const i01 = r * stride + (c + 1);
      tris.set([i00, i10, i11, i00, i11, i01], ti);
      ti += 6;
      wire.set([i00, i01, i00, i10], wi);
      wi += 4;
    }
  }
  // krawędzie: (u, v, indeks wierzchołka rdzenia) dla k = 0..N
  const edges = [
    (k) => [uLin[k], 0.0, k],
    (k) => [1.0, vLin[k], k * stride + N],
    (k) => [uLin[N - k], 1.0, N * stride + (N - k)],
    (k) => [0.0, vLin[N - k], (N - k) * stride],
  ];
  let offset = nCore;
  for (const edge of edges) {
    const top = new Array(N + 1);
    for (let k = 0; k <= N; k++) {
      const [eu, ev, idx] = edge(k);
      const vk = (offset + k) * 3;
      verts[vk] = eu;
      verts[vk + 1] = ev;
      verts[vk + 2] = 1.0;
      top[k] = idx;
    }
    for (let k = 0; k < N; k++) {
      const t0 = top[k];
      const t1 = top[k + 1];
      const b0 = offset + k;
      const b1 = offset + k + 1;
      tris.set([t0, t1, b1, t0, b1, b0], ti);
      ti += 6;
    }
    offset += N + 1;
  }
  return { verts, tris, wire };
}

export class TerrainRenderer {
  /**
   * @param {WebGL2RenderingContext} gl
   * @param {object} catalog odpowiedź lunar_surface.catalog
   */
  constructor(gl, catalog) {
    this.gl = gl;
    this.catalog = catalog;
    // geografia.py:1527-1536
    this.H = catalog.dem.height;
    this.W = catalog.dem.width;
    this.AH = catalog.albedo.height;
    this.AW = catalog.albedo.width;
    this.albedoIsU8 = catalog.albedo_is_u8;
    this.albedoScale = catalog.albedo_scale;
    this.demDlatRad = Math.PI / this.H;
    this.demDlonRad = (2.0 * Math.PI) / this.W;

    // geografia.py:1538-1550
    this.azGrid = linspace(0.0, 2.0 * Math.PI, 721);
    this.nAz = this.azGrid.length - 1;
    const rootLats = linspace(0.5 * Math.PI, -0.5 * Math.PI, 9);
    const rootLons = linspace(-Math.PI, Math.PI, 17);
    const n = 8 * 16;
    this.roots = { lat0: new Float64Array(n), lat1: new Float64Array(n), lon0: new Float64Array(n), lon1: new Float64Array(n) };
    for (let b = 0; b < 8; b++) {
      for (let j = 0; j < 16; j++) {
        const k = b * 16 + j;
        this.roots.lat0[k] = rootLats[b];
        this.roots.lat1[k] = rootLats[b + 1];
        this.roots.lon0[k] = rootLons[j];
        this.roots.lon1[k] = rootLons[j + 1];
      }
    }

    // geografia.py:1551-1572
    this.cachedLat = null;
    this.cachedLon = null;
    this.cachedEyeHeightM = null;
    this.horizonAlt = null;
    this.obsElevKm = 0.0;
    this.obsRadiusKm = R_MOON;
    this.eyeKm = 0.015;
    this.rMaxKm = 450.0;
    this.up0 = [0.0, 0.0, 1.0];
    this.east0 = [0.0, 1.0, 0.0];
    this.north0 = [1.0, 0.0, 0.0];
    this.obsBody = [0.0, 0.0, R_MOON];
    this.quadCount = 0;
    this.drawnCount = 0;
    this.lodTau = TAU_PX;
    this.lodTauUsed = TAU_PX;
    this.geom = null;

    this._initGpu();
  }

  /** HUD: drawn_count · PATCH_N² · 2 (geografia.py:2949). */
  get nTris() {
    return this.drawnCount * (PATCH_N * PATCH_N * 2);
  }

  // geografia.py:1625-1732 (bez tekstur — te są w TileWindow)
  _initGpu() {
    const { gl } = this;
    this.progTerrain = createProgram(gl, TERRAIN_VS, TERRAIN_FS);
    this.progHorizon = createProgram(gl, HORIZON_VS, HORIZON_FS);

    const { verts, tris, wire } = buildStaticPatchGeometry();
    this.nPatchTris = tris.length;
    this.nPatchWire = wire.length;

    this.vaoTerrain = gl.createVertexArray();
    gl.bindVertexArray(this.vaoTerrain);

    this.vboPatch = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vboPatch);
    gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW);
    const a = this.progTerrain.a;
    gl.enableVertexAttribArray(a.in_uv);
    gl.vertexAttribPointer(a.in_uv, 2, gl.FLOAT, false, 12, 0);
    gl.enableVertexAttribArray(a.in_is_skirt);
    gl.vertexAttribPointer(a.in_is_skirt, 1, gl.FLOAT, false, 12, 8);

    this.vboInstances = gl.createBuffer();
    this.instBuf = new Float32Array(MAX_PATCHES * 5);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vboInstances);
    gl.bufferData(gl.ARRAY_BUFFER, this.instBuf.byteLength, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(a.in_lat_lon);
    gl.vertexAttribPointer(a.in_lat_lon, 4, gl.FLOAT, false, 20, 0);
    gl.vertexAttribDivisor(a.in_lat_lon, 1);
    gl.enableVertexAttribArray(a.in_skirt_km);
    gl.vertexAttribPointer(a.in_skirt_km, 1, gl.FLOAT, false, 20, 16);
    gl.vertexAttribDivisor(a.in_skirt_km, 1);

    this.iboTris = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.iboTris);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, tris, gl.STATIC_DRAW);

    this.iboWire = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.iboWire);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, wire, gl.STATIC_DRAW);

    this.vaoHorizon = gl.createVertexArray();
    this.vboHorizon = gl.createBuffer();
    gl.bindVertexArray(this.vaoHorizon);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vboHorizon);
    gl.bufferData(gl.ARRAY_BUFFER, this.azGrid.length * 3 * 4, gl.DYNAMIC_DRAW);
    const ah = this.progHorizon.a;
    gl.enableVertexAttribArray(ah.in_enu);
    gl.vertexAttribPointer(ah.in_enu, 3, gl.FLOAT, false, 12, 0);

    gl.bindVertexArray(null);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
  }

  /**
   * Obserwator z lunar_surface.observer. Przypisania jak update_observer (geografia.py:1899-1922);
   * grunt, nachylenie i profil horyzontu (:1924-1956) pochodzą z serwera.
   */
  setObserver(geom) {
    this.geom = geom;
    this.cachedLat = geom.observer.lat_deg;
    this.cachedLon = geom.observer.lon_deg;
    this.cachedEyeHeightM = geom.eye_height_m;

    // geografia.py:1910-1920
    const eyeKm = geom.eye_height_m / 1000.0;
    this.eyeKm = eyeKm;
    this.rMaxKm = geom.r_max_km;
    const lat0 = this.cachedLat * DEG;
    const lon0 = this.cachedLon * DEG;
    const up0 = [Math.cos(lat0) * Math.cos(lon0), Math.cos(lat0) * Math.sin(lon0), Math.sin(lat0)];
    const east0 = [-Math.sin(lon0), Math.cos(lon0), 0.0];
    const north0 = cross(up0, east0);
    this.up0 = up0;
    this.east0 = east0;
    this.north0 = north0;

    // geografia.py:1925-1929
    this.obsSlopeDeg = geom.slope_deg;
    this.obsSlopeDir = geom.slope_dir;
    this.obsElevKm = geom.observer_elevation_km;
    this.obsRadiusKm = geom.observer_radius_km;
    this.obsBody = up0.map((v) => this.obsRadiusKm * v);

    this.horizonAlt = Float64Array.from(geom.horizon.alt_deg, (d) => d * DEG);

    // geografia.py:2251-2257: wierzchołki linii horyzontu (stałe dla obserwatora, więc wgrywane tu, nie co klatkę)
    const hp = new Float32Array(this.azGrid.length * 3);
    for (let i = 0; i < this.azGrid.length; i++) {
      const ca = Math.cos(this.horizonAlt[i]);
      hp[i * 3] = ca * Math.cos(this.azGrid[i]);
      hp[i * 3 + 1] = ca * Math.sin(this.azGrid[i]);
      hp[i * 3 + 2] = Math.sin(this.horizonAlt[i]);
    }
    const { gl } = this;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vboHorizon);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, hp);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
  }

  // geografia.py:1958-1959
  /** np.interp(az % 2π, az_grid, horizon_alt) [rad]. */
  horizonAt(azRad) {
    const fp = this.horizonAlt;
    if (!fp) return 0.0;
    const xp = this.azGrid;
    const x = ((azRad % TWO_PI) + TWO_PI) % TWO_PI;
    const last = xp.length - 1;
    if (x >= xp[last]) return fp[last];
    if (x <= xp[0]) return fp[0];
    let j = Math.min(last - 1, Math.max(0, Math.floor((x / xp[last]) * last)));
    while (j > 0 && xp[j] > x) j--;
    while (j < last - 1 && xp[j + 1] <= x) j++;
    if (xp[j] === x) return fp[j];
    const slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]);
    return slope * (x - xp[j]) + fp[j];
  }

  // geografia.py:1996-2002
  /** Baza kamery (fwd, right, up) w [North, East, Up] i w układzie ciała. */
  cameraBody(camAlt, camAz) {
    const fwd = [Math.cos(camAlt) * Math.cos(camAz), Math.cos(camAlt) * Math.sin(camAz), Math.sin(camAlt)];
    const right = [-Math.sin(camAz), Math.cos(camAz), 0.0];
    const camUp = [-Math.sin(camAlt) * Math.cos(camAz), -Math.sin(camAlt) * Math.sin(camAz), Math.cos(camAlt)];
    const n = this.north0;
    const e = this.east0;
    const u = this.up0;
    const toBody = (v) => [0, 1, 2].map((j) => v[0] * n[j] + v[1] * e[j] + v[2] * u[j]);
    return { fwd, right, camUp, fwdB: toBody(fwd), rightB: toBody(right), upB: toBody(camUp) };
  }

  // geografia.py:2004-2115
  /** Przejście podziału quadtree PQS; zwraca liście {lat0, lat1, lon0, lon1, skirt} w kolejności numpy. */
  _lodPass(focal, tanX, tanY, fwdB, rightB, upB, tau) {
    const up0 = this.up0;
    const obs = this.obsBody;
    const rMax = this.rMaxKm;
    const h2 = this.eyeKm * this.eyeKm;
    const invX = 1.0 / Math.sqrt(1.0 + tanX * tanX);
    const invY = 1.0 / Math.sqrt(1.0 + tanY * tanY);

    const minCellDlat = MIN_CELL_SCALE * this.demDlatRad;
    const minCellDlon = MIN_CELL_SCALE * this.demDlonRad;

    let lat0 = Array.from(this.roots.lat0);
    let lat1 = Array.from(this.roots.lat1);
    let lon0 = Array.from(this.roots.lon0);
    let lon1 = Array.from(this.roots.lon1);
    let depth = new Array(lat0.length).fill(0);
    const out = { lat0: [], lat1: [], lon0: [], lon1: [], skirt: [] };

    while (lat0.length) {
      const spIdx = [];
      const spR = [];
      const spC = [];
      for (let i = 0; i < lat0.length; i++) {
        const la0 = lat0[i];
        const la1 = lat1[i];
        const lo0 = lon0[i];
        const lo1 = lon1[i];
        const dlat = la0 - la1;
        const dlon = lo1 - lo0;
        const ns = R_MOON * dlat;
        const cosEq = (la0 > 0.0 && la1 < 0.0) ? 1.0 : Math.max(Math.cos(la0), Math.cos(la1));
        const ew = R_MOON * dlon * cosEq;

        const latc = 0.5 * (la0 + la1);
        const lonc = 0.5 * (lo0 + lo1);
        const clc = Math.cos(latc);
        const ux = clc * Math.cos(lonc);
        const uy = clc * Math.sin(lonc);
        const uz = Math.sin(latc);

        const arc = R_MOON * Math.acos(clip(ux * up0[0] + uy * up0[1] + uz * up0[2], -1.0, 1.0));
        const half = 0.5 * Math.hypot(ns, ew);
        const dPoz = Math.max(arc - half, 0.0);

        const px = R_MOON * ux - obs[0];
        const py = R_MOON * uy - obs[1];
        const pz = R_MOON * uz - obs[2];
        const zc = px * fwdB[0] + py * fwdB[1] + pz * fwdB[2];
        const xc = px * rightB[0] + py * rightB[1] + pz * rightB[2];
        const yc = px * upB[0] + py * upB[1] + pz * upB[2];
        const rad = half + R_MOON * (1.0 - Math.cos(Math.min(half / R_MOON, Math.PI))) + 14.0;

        const keep = (
          (dPoz <= rMax)
          && (zc >= -rad)
          && ((zc * tanX + xc) * invX >= -rad)
          && ((zc * tanX - xc) * invX >= -rad)
          && ((zc * tanY + yc) * invY >= -rad)
          && ((zc * tanY - yc) * invY >= -rad)
        );
        if (!keep) continue;

        const d = Math.sqrt(dPoz * dPoz + h2);
        const cellSizePx = (Math.max(ns, ew) / PATCH_N) * focal / Math.max(d, 1e-9);

        const canR = dlat > (minCellDlat * PATCH_N);
        const canC = dlon > (minCellDlon * PATCH_N);
        const splitR = !(ew > 1.5 * ns) && canR;
        const splitC = !(ns > 1.5 * ew) && canC;
        const stuck = (!splitR && !splitC) || (depth[i] >= 16);

        const leaf = (cellSizePx <= tau) || stuck;
        if (leaf) {
          out.lat0.push(la0);
          out.lat1.push(la1);
          out.lon0.push(lo0);
          out.lon1.push(lo1);
          out.skirt.push(clip(0.035 * Math.max(ns, ew), 0.002, 4.5));
        } else {
          spIdx.push(i);
          spR.push(splitR);
          spC.push(splitC);
        }
      }

      if (!spIdx.length) break;

      // dzieci w kolejności numpy: najpierw wszystkie (0,0), potem (1,0), (0,1), (1,1)
      const nLa0 = [];
      const nLa1 = [];
      const nLo0 = [];
      const nLo1 = [];
      const nDp = [];
      for (const [dr, dc] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
        for (let k = 0; k < spIdx.length; k++) {
          const sr = spR[k];
          const sc = spC[k];
          if ((dr && !sr) || (dc && !sc)) continue;
          const i = spIdx[k];
          const la0 = lat0[i];
          const la1 = lat1[i];
          const lo0 = lon0[i];
          const lo1 = lon1[i];
          const lam = 0.5 * (la0 + la1);
          const lom = 0.5 * (lo0 + lo1);
          nLa0.push(sr ? (dr ? lam : la0) : la0);
          nLa1.push(sr ? (dr ? la1 : lam) : la1);
          nLo0.push(sc ? (dc ? lom : lo0) : lo0);
          nLo1.push(sc ? (dc ? lo1 : lom) : lo1);
          nDp.push(depth[i] + 1);
        }
      }

      if (!nLa0.length) break;
      lat0 = nLa0;
      lat1 = nLa1;
      lon0 = nLo0;
      lon1 = nLo1;
      depth = nDp;
    }
    return out;
  }

  // geografia.py:2117-2139
  /** Wybór paczek LOD w budżecie MAX_PATCHES, z histerezą lodTau. */
  selectLod(cw, ch, camAlt, camAz, fov) {
    const focal = (ch / 2.0) / Math.tan(fov / 2.0);
    const margin = 90.0;
    const tanX = (cw / 2.0 + margin) / focal;
    const tanY = (ch / 2.0 + margin) / focal;
    const { fwdB, rightB, upB } = this.cameraBody(camAlt, camAz);

    let tau = Math.max(TAU_PX, this.lodTau);
    let patches = this._lodPass(focal, tanX, tanY, fwdB, rightB, upB, tau);
    const n = patches.lat0.length;
    if (n > MAX_PATCHES) {
      tau *= Math.sqrt(n / MAX_PATCHES);
      patches = this._lodPass(focal, tanX, tanY, fwdB, rightB, upB, tau);
      this.lodTau = tau;
    } else if (n < 0.6 * MAX_PATCHES && tau > TAU_PX) {
      this.lodTau = Math.max(TAU_PX, tau * Math.sqrt(Math.max(1, n) / (0.8 * MAX_PATCHES)));
    } else {
      this.lodTau = tau;
    }

    this.lodTauUsed = tau;
    this.quadCount = patches.lat0.length * (PATCH_N * PATCH_N);
    return patches;
  }

  // geografia.py:2141-2270
  /** draw_3d: instancjonowane paczki terenu i linia horyzontu (2 px = 4 przejścia z offsetem). */
  draw({
    cw, ch, camAlt, camAz, fov, sunAlt, sunAz, earthAlt, earthAz = 0.0,
    sunEffectiveVis = 1.0, eclipseRedGlow = 0.0, wireframe = false, showHorizonLine = true,
    demWin, albedoWin,
  }) {
    const { gl } = this;
    const { fwd, right, camUp } = this.cameraBody(camAlt, camAz);

    const nearZ = 0.00005;   // 5 cm (prevents near-plane clipping at 2 m eye height)
    const farZ = Math.max(2000.0, this.rMaxKm * 2.0);
    const halfCw = cw / 2.0;
    const halfCh = ch / 2.0;
    const focal = halfCh / Math.tan(fov / 2.0);
    const tanX = halfCw / focal;
    const tanY = halfCh / focal;

    const p = this.selectLod(cw, ch, camAlt, camAz, fov);
    const nPatches = Math.min(p.lat0.length, MAX_PATCHES);

    if (nPatches > 0) {
      const inst = this.instBuf;
      for (let k = 0; k < nPatches; k++) {
        inst[k * 5] = p.lat0[k];
        inst[k * 5 + 1] = p.lat1[k];
        inst[k * 5 + 2] = p.lon0[k];
        inst[k * 5 + 3] = p.lon1[k];
        inst[k * 5 + 4] = p.skirt[k];
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vboInstances);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, inst, 0, nPatches * 5);

      const obsLatR = this.cachedLat * DEG;
      const obsLonR = this.cachedLon * DEG;
      const obsTotalElev = this.obsElevKm + this.eyeKm;

      const sunEnu = [
        Math.cos(sunAlt) * Math.cos(sunAz),
        Math.cos(sunAlt) * Math.sin(sunAz),
        Math.sin(sunAlt),
      ];
      const earthEnu = [
        Math.cos(earthAlt) * Math.cos(earthAz),
        Math.cos(earthAlt) * Math.sin(earthAz),
        Math.sin(earthAlt),
      ];
      const earthshine = 0.045 * Math.max(0.0, Math.sin(earthAlt));
      const tint = [
        1.0 + 0.85 * eclipseRedGlow,
        1.0 - 0.15 * eclipseRedGlow,
        1.0 - 0.35 * eclipseRedGlow,
      ];

      gl.activeTexture(gl.TEXTURE0 + demWin.unit);
      gl.bindTexture(gl.TEXTURE_2D, demWin.texture);
      gl.activeTexture(gl.TEXTURE0 + albedoWin.unit);
      gl.bindTexture(gl.TEXTURE_2D, albedoWin.texture);

      gl.useProgram(this.progTerrain.program);
      const u = this.progTerrain.u;
      gl.uniform1i(u.u_tex_dem, demWin.unit);
      gl.uniform1i(u.u_tex_albedo, albedoWin.unit);
      gl.uniform2f(u.u_dem_size, this.W, this.H);
      gl.uniform1i(u.u_albedo_raw_u8, this.albedoIsU8 ? 1 : 0);
      gl.uniform1f(u.u_albedo_scale, this.albedoScale);
      // okna z kafli (odchylenie 1): DEM — demWin, albedo — albedoWin + globalny rozmiar albedo
      const dw = demWin.uniforms();
      gl.uniform2f(u.u_dem_origin, dw.origin[0], dw.origin[1]);
      gl.uniform2f(u.u_dem_win, dw.size[0], dw.size[1]);
      gl.uniform1i(u.u_dem_full, dw.full);
      const aw = albedoWin.uniforms();
      gl.uniform2f(u.u_alb_origin, aw.origin[0], aw.origin[1]);
      gl.uniform2f(u.u_alb_win, aw.size[0], aw.size[1]);
      gl.uniform2f(u.u_alb_size, this.AW, this.AH);

      gl.uniform1f(u.u_obs_lat, obsLatR);
      gl.uniform1f(u.u_obs_lon, obsLonR);
      gl.uniform1f(u.u_obs_elev, obsTotalElev);
      gl.uniform1f(u.u_sin_obs_lat, Math.sin(obsLatR));
      gl.uniform1f(u.u_cos_obs_lat, Math.cos(obsLatR));

      gl.uniform3f(u.u_fwd, fwd[0], fwd[1], fwd[2]);
      gl.uniform3f(u.u_right, right[0], right[1], right[2]);
      gl.uniform3f(u.u_cam_up, camUp[0], camUp[1], camUp[2]);
      gl.uniform1f(u.u_tan_x, tanX);
      gl.uniform1f(u.u_tan_y, tanY);
      gl.uniform1f(u.u_near, nearZ);
      gl.uniform1f(u.u_far, farZ);

      gl.uniform3f(u.u_sun_enu, sunEnu[0], sunEnu[1], sunEnu[2]);
      gl.uniform3f(u.u_earth_enu, earthEnu[0], earthEnu[1], earthEnu[2]);
      gl.uniform1f(u.u_sun_effective_vis, sunEffectiveVis);
      gl.uniform1f(u.u_earthshine, earthshine);
      gl.uniform3f(u.u_tint, tint[0], tint[1], tint[2]);
      gl.uniform3f(u.u_wire_add, 0.0, 0.0, 0.0);

      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.CULL_FACE);
      gl.frontFace(gl.CCW);
      gl.disable(gl.BLEND);

      gl.bindVertexArray(this.vaoTerrain);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.iboTris);
      if (wireframe) {
        gl.enable(gl.POLYGON_OFFSET_FILL);
        gl.polygonOffset(1.0, 1.0);
        gl.drawElementsInstanced(gl.TRIANGLES, this.nPatchTris, gl.UNSIGNED_INT, 0, nPatches);
        gl.disable(gl.POLYGON_OFFSET_FILL);
        gl.uniform3f(u.u_wire_add, 35.0 / 255.0, 35.0 / 255.0, 40.0 / 255.0);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.iboWire);
        gl.drawElementsInstanced(gl.LINES, this.nPatchWire, gl.UNSIGNED_INT, 0, nPatches);
      } else {
        gl.drawElementsInstanced(gl.TRIANGLES, this.nPatchTris, gl.UNSIGNED_INT, 0, nPatches);
      }

      this.drawnCount = nPatches;
    } else {
      this.drawnCount = 0;
    }

    if (showHorizonLine && this.horizonAlt !== null) {
      gl.disable(gl.DEPTH_TEST);
      gl.disable(gl.CULL_FACE);
      gl.useProgram(this.progHorizon.program);
      const uh = this.progHorizon.u;
      gl.uniform3f(uh.u_fwd, fwd[0], fwd[1], fwd[2]);
      gl.uniform3f(uh.u_right, right[0], right[1], right[2]);
      gl.uniform3f(uh.u_cam_up, camUp[0], camUp[1], camUp[2]);
      gl.uniform1f(uh.u_tan_x, tanX);
      gl.uniform1f(uh.u_tan_y, tanY);
      gl.uniform2f(uh.u_viewport, cw, ch);
      gl.bindVertexArray(this.vaoHorizon);
      // glLineWidth(2.0) → odchylenie 4: cztery LINE_STRIP przesunięte o (0,0), (1,0), (0,1), (1,1) px
      for (const [ox, oy] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
        gl.uniform2f(uh.u_offset_px, ox, oy);
        gl.drawArrays(gl.LINE_STRIP, 0, this.azGrid.length);
      }
    }
    gl.bindVertexArray(null);
  }
}
