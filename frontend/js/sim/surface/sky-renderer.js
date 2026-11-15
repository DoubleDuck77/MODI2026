// Niebo trybu Powierzchnia: port GPURenderer z geografia.py (geografia.py:846-1205) do WebGL2.
// Gwiazdy (punkty 1 px), siatka wysokości 0/30/60°, teleskopowe Słońce i Ziemia jako prostokąt
// w pikselach ekranu z shaderem per piksel; Ziemia z teksturami dnia, nocy (mipy liczone na CPU
// jak build_night_mipmaps) i chmur. Bez HUD-u na teksturze — HUD rysuje canvas 2D (hud.js).

import { createProgram } from './gl.js';
import { EARTH_FS, GRID_FS, GRID_VS, QUAD_VS, STAR_FS, STAR_VS, SUN_FS } from './shaders.js';

// geografia.py:432-490 (kandydaci :451-474): load_earth_textures sprawdza dokładne nazwy po kolei. Dzień i chmury to pliki
// *8K, a noc to earth_night.jpg: earrth_night8K.jpg (literówka) nie pasuje do żadnego kandydata.
export const EARTH_TEXTURES = {
  day: '/textures/earth_day8K.jpg',
  night: '/textures/earth_night.jpg',
  clouds: '/textures/earth_clouds8K.jpg',
};

const f32 = Math.fround;
const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm3 = (a) => Math.sqrt(dot3(a, a));
const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

// geografia.py:414-429
/**
 * build_night_mipmaps na RGB (w·h·3 bajtów): każdy poziom to 0.45·średnia + 0.55·max bloków 2×2,
 * dopóki h ≥ 256 i w ≥ 512. Arytmetyka float32 jak w numpy, potem obcięcie do uint8.
 * @returns {{w: number, h: number, data: Uint8Array}[]}
 */
export function buildNightMipmaps(w, h, rgb) {
  const mips = [{ w, h, data: rgb }];
  let cur = mips[0];
  const k45 = f32(0.45);
  const k55 = f32(0.55);
  while (cur.h >= 256 && cur.w >= 512) {
    const nh = Math.floor(cur.h / 2);   // (h // 2) * 2 wierszy → h // 2 bloków
    const nw = Math.floor(cur.w / 2);
    const src = cur.data;
    const stride = cur.w * 3;
    const out = new Uint8Array(nw * nh * 3);
    for (let y = 0; y < nh; y++) {
      const r0 = 2 * y * stride;
      const r1 = r0 + stride;
      for (let x = 0; x < nw; x++) {
        for (let k = 0; k < 3; k++) {
          const a = src[r0 + 6 * x + k];
          const b = src[r0 + 6 * x + 3 + k];
          const c = src[r1 + 6 * x + k];
          const d = src[r1 + 6 * x + 3 + k];
          const mean = (a + b + c + d) / 4;   // dokładne także w float32 (suma ≤ 1020)
          const mx = Math.max(a, b, c, d);
          const v = f32(f32(k45 * mean) + f32(k55 * mx));
          out[(y * nw + x) * 3 + k] = Math.trunc(Math.min(255, Math.max(0, v)));
        }
      }
    }
    cur = { w: nw, h: nh, data: out };
    mips.push(cur);
  }
  return mips;
}

/** Dekodowanie JPEG: createImageBitmap (bez profilu ICC, jak pygame) → canvas → getImageData (RGBA). */
async function decodeImage(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  const bmp = await createImageBitmap(await res.blob(), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  const w = bmp.width;
  const h = bmp.height;
  let canvas;
  if (typeof OffscreenCanvas !== 'undefined') {
    canvas = new OffscreenCanvas(w, h);
  } else {
    canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
  }
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0);
  bmp.close();
  const rgba = ctx.getImageData(0, 0, w, h).data;
  canvas.width = 1;   // zwolnij bufor canvasu od razu
  return { w, h, rgba };
}

/** RGBA → kanały [0..n) (pygame.surfarray.array3d → RGB; chmury: kanał 0). */
function pickChannels(rgba, n) {
  const px = rgba.length >> 2;
  const out = new Uint8Array(px * n);
  for (let i = 0, j = 0; i < px; i++) {
    for (let k = 0; k < n; k++) out[j++] = rgba[i * 4 + k];
  }
  return out;
}

export class SkyRenderer {
  /**
   * @param {WebGL2RenderingContext} gl
   * @param {{ecliptic_xyz: number[][], brightness: number[]}} stars odpowiedź lunar_surface.stars
   */
  constructor(gl, stars) {
    this.gl = gl;

    // geografia.py:850-872 — 1. gwiazdy: [x, y, z, mag/255], stride 16
    this.progStars = createProgram(gl, STAR_VS, STAR_FS);
    this.nStars = stars.ecliptic_xyz.length;
    const starData = new Float32Array(this.nStars * 4);
    for (let i = 0; i < this.nStars; i++) {
      const v = stars.ecliptic_xyz[i];
      starData[i * 4] = v[0];
      starData[i * 4 + 1] = v[1];
      starData[i * 4 + 2] = v[2];
      starData[i * 4 + 3] = stars.brightness[i] / 255.0;   // float32(mag) / 255 (dzielenie dokładne po zaokrągleniu)
    }
    this.vaoStars = gl.createVertexArray();
    this.vboStars = gl.createBuffer();
    gl.bindVertexArray(this.vaoStars);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vboStars);
    gl.bufferData(gl.ARRAY_BUFFER, starData, gl.STATIC_DRAW);
    const as = this.progStars.a;
    gl.enableVertexAttribArray(as.in_ecl);
    gl.vertexAttribPointer(as.in_ecl, 3, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(as.in_mag);
    gl.vertexAttribPointer(as.in_mag, 1, gl.FLOAT, false, 16, 12);

    // geografia.py:874-903 — 2. siatka: okręgi alt 0/30/60°, co 5° azymutu, odcinki LINES
    this.progGrid = createProgram(gl, GRID_VS, GRID_FS);
    gl.useProgram(this.progGrid.program);
    gl.uniform4f(this.progGrid.u.u_color, 25.0 / 255.0, 35.0 / 255.0, 50.0 / 255.0, 1.0);
    const segs = [];
    for (let aDeg = 0; aDeg < 90; aDeg += 30) {
      const aRad = aDeg * (Math.PI / 180);
      const ca = Math.cos(aRad);
      const sa = Math.sin(aRad);
      const pts = [];
      for (let z = 0; z < 365; z += 5) {
        const zr = z * (Math.PI / 180);
        pts.push([ca * Math.cos(zr), ca * Math.sin(zr), sa]);
      }
      for (let i = 0; i < pts.length - 1; i++) segs.push(...pts[i], ...pts[i + 1]);
    }
    const gridArr = new Float32Array(segs);
    this.nGridVerts = gridArr.length / 3;
    this.vaoGrid = gl.createVertexArray();
    this.vboGrid = gl.createBuffer();
    gl.bindVertexArray(this.vaoGrid);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vboGrid);
    gl.bufferData(gl.ARRAY_BUFFER, gridArr, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(this.progGrid.a.in_enu);
    gl.vertexAttribPointer(this.progGrid.a.in_enu, 3, gl.FLOAT, false, 12, 0);

    // geografia.py:905-956 — 3. dynamiczny prostokąt ekranu (Słońce / Ziemia)
    this.progSun = createProgram(gl, QUAD_VS, SUN_FS);
    this.progEarth = createProgram(gl, QUAD_VS, EARTH_FS);
    this.vboDynQuad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vboDynQuad);
    gl.bufferData(gl.ARRAY_BUFFER, 4 * 4 * 4, gl.DYNAMIC_DRAW);
    this.quadVerts = new Float32Array(16);
    const makeQuadVao = (prog) => {
      const vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vboDynQuad);
      const lp = prog.a.in_pos;
      const lu = prog.a.in_uv;   // v_uv nie jest czytane przez FS — atrybut może zostać usunięty (-1)
      gl.enableVertexAttribArray(lp);
      gl.vertexAttribPointer(lp, 2, gl.FLOAT, false, 16, 0);
      if (lu !== undefined && lu >= 0) {
        gl.enableVertexAttribArray(lu);
        gl.vertexAttribPointer(lu, 2, gl.FLOAT, false, 16, 8);
      }
      return vao;
    };
    this.vaoSun = makeQuadVao(this.progSun);
    this.vaoEarth = makeQuadVao(this.progEarth);
    gl.bindVertexArray(null);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);

    // geografia.py:959-1015 — 4. tekstury Ziemi; do czasu wczytania atrapy 1×1 jak bez plików
    this.hasDay = false;
    this.hasNight = false;
    this.hasClouds = false;
    this.nightBaseW = 1;
    this.nightMaxMip = 0;
    this.texturesSettled = false;
    const black3 = new Uint8Array([0, 0, 0]);
    this.texEarthDay = this._newTexture();
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB8, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, black3);
    this.texEarthNight = this._newTexture();
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB8, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, black3);
    this.texEarthClouds = this._newTexture();
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, 1, 1, 0, gl.RED, gl.UNSIGNED_BYTE, new Uint8Array([0]));
    gl.bindTexture(gl.TEXTURE_2D, null);
  }

  /** Nowa tekstura z WRAP_S = REPEAT, WRAP_T = CLAMP_TO_EDGE (wszystkie trzy w GPURenderer.__init__). */
  _newTexture() {
    const { gl } = this;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return tex;
  }

  /**
   * load_earth_textures + wgranie jak GPURenderer.__init__ (geografia.py:432-490, 959-1015). Brak pliku
   * zostawia atrapę i u_has_* = 0 (wtedy shader rysuje zastępczą Ziemię, jak skrypt).
   */
  async loadEarthTextures() {
    const { gl } = this;
    try {
      const img = await decodeImage(EARTH_TEXTURES.day);
      const rgb = pickChannels(img.rgba, 3);
      gl.bindTexture(gl.TEXTURE_2D, this.texEarthDay);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB8, img.w, img.h, 0, gl.RGB, gl.UNSIGNED_BYTE, rgb);
      this.hasDay = true;
    } catch (e) {
      console.warn('[WARNING] Missing Earth day texture', e);
    }
    try {
      const img = await decodeImage(EARTH_TEXTURES.night);
      const mips = buildNightMipmaps(img.w, img.h, pickChannels(img.rgba, 3));
      gl.bindTexture(gl.TEXTURE_2D, this.texEarthNight);
      this.nightBaseW = mips[0].w;
      this.nightMaxMip = mips.length - 1;
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAX_LEVEL, this.nightMaxMip);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, this.nightMaxMip > 0 ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      mips.forEach((m, lvl) => {
        gl.texImage2D(gl.TEXTURE_2D, lvl, gl.RGB8, m.w, m.h, 0, gl.RGB, gl.UNSIGNED_BYTE, m.data);
      });
      this.hasNight = true;
      this.nightMips = mips;   // do weryfikacji (root._debug)
    } catch (e) {
      console.warn('[WARNING] Missing Earth night (city lights) texture', e);
    }
    try {
      const img = await decodeImage(EARTH_TEXTURES.clouds);
      const ch0 = pickChannels(img.rgba, 1);
      gl.bindTexture(gl.TEXTURE_2D, this.texEarthClouds);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, img.w, img.h, 0, gl.RED, gl.UNSIGNED_BYTE, ch0);
      this.hasClouds = true;
    } catch (e) {
      console.warn('[WARNING] Missing Earth clouds texture', e);
    }
    gl.bindTexture(gl.TEXTURE_2D, null);
    this.texturesSettled = true;
  }

  // geografia.py:1052-1064
  _uploadScreenRect(x0, y0, x1, y1, cw, ch) {
    const { gl } = this;
    const nx0 = (x0 / cw) * 2.0 - 1.0;
    const nx1 = (x1 / cw) * 2.0 - 1.0;
    const ny0 = 1.0 - (y0 / ch) * 2.0;
    const ny1 = 1.0 - (y1 / ch) * 2.0;
    this.quadVerts.set([
      nx0, ny0, 0.0, 0.0,
      nx0, ny1, 0.0, 1.0,
      nx1, ny0, 1.0, 0.0,
      nx1, ny1, 1.0, 1.0,
    ]);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vboDynQuad);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.quadVerts);
  }

  // geografia.py:1066-1083
  /**
   * Gwiazdy. view.eclipticToEnu = LunarSky.ecliptic_to_enu (wiersze N, E, U) jako u_R_body, a osie
   * u_north/east/up = (1,0,0), (0,1,0), (0,0,1): iloczyny skalarne są te same co R_body z bazą ciała.
   * uniformMatrix3fv bez transpozycji dostaje macierz kolumnami (jak R_body.T w draw_stars).
   */
  drawStars(view) {
    const { gl } = this;
    const M = view.eclipticToEnu;
    gl.useProgram(this.progStars.program);
    const u = this.progStars.u;
    gl.uniformMatrix3fv(u.u_R_body, false, new Float32Array([
      M[0][0], M[1][0], M[2][0],
      M[0][1], M[1][1], M[2][1],
      M[0][2], M[1][2], M[2][2],
    ]));
    gl.uniform3f(u.u_north, 1.0, 0.0, 0.0);
    gl.uniform3f(u.u_east, 0.0, 1.0, 0.0);
    gl.uniform3f(u.u_up, 0.0, 0.0, 1.0);
    gl.uniform3f(u.u_fwd, view.fwd[0], view.fwd[1], view.fwd[2]);
    gl.uniform3f(u.u_right, view.right[0], view.right[1], view.right[2]);
    gl.uniform3f(u.u_cam_up, view.camUp[0], view.camUp[1], view.camUp[2]);
    gl.uniform1f(u.u_cw, view.cw);
    gl.uniform1f(u.u_ch, view.ch);
    gl.uniform1f(u.u_focal, view.focal);
    gl.bindVertexArray(this.vaoStars);
    gl.drawArrays(gl.POINTS, 0, this.nStars);
    gl.bindVertexArray(null);
  }

  // geografia.py:1085-1096
  drawGrid(view) {
    const { gl } = this;
    gl.useProgram(this.progGrid.program);
    const u = this.progGrid.u;
    gl.uniform3f(u.u_fwd, view.fwd[0], view.fwd[1], view.fwd[2]);
    gl.uniform3f(u.u_right, view.right[0], view.right[1], view.right[2]);
    gl.uniform3f(u.u_cam_up, view.camUp[0], view.camUp[1], view.camUp[2]);
    gl.uniform1f(u.u_tan_x, (view.cw / 2.0) / view.focal);
    gl.uniform1f(u.u_tan_y, (view.ch / 2.0) / view.focal);
    gl.bindVertexArray(this.vaoGrid);
    gl.drawArrays(gl.LINES, 0, this.nGridVerts);
    gl.bindVertexArray(null);
  }

  // geografia.py:1098-1119
  /** Słońce: sun = {sx, sy, rExact} z project_point i tan(ang_sun)·focal/z_cam. */
  drawTelescopicSun(view, sun) {
    const { cw, ch } = view;
    const { sx, sy } = sun;
    const rSun = Math.max(4.0, sun.rExact);
    const haloMult = rSun < 20.0 ? 3.8 : 2.5;
    const haloR = Math.min(Math.max(rSun * haloMult, 22.0), Math.max(cw, ch));

    const x0 = Math.max(0.0, sx - haloR);
    const x1 = Math.min(cw, sx + haloR + 1.0);
    const y0 = Math.max(0.0, sy - haloR);
    const y1 = Math.min(ch, sy + haloR + 1.0);
    if (x1 <= x0 || y1 <= y0) return;

    const { gl } = this;
    this._uploadScreenRect(x0, y0, x1, y1, cw, ch);
    gl.useProgram(this.progSun.program);
    const u = this.progSun.u;
    gl.uniform1f(u.u_sx, sx);
    gl.uniform1f(u.u_sy, sy);
    gl.uniform1f(u.u_r_sun, rSun);
    gl.uniform1f(u.u_halo_mult, haloMult);
    gl.uniform1f(u.u_ch, ch);
    gl.bindVertexArray(this.vaoSun);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);
  }

  // geografia.py:1121-1194
  /**
   * Ziemia: earth = {ex, ey, rExact, dirEnu, cloudOffset}; sky = stan LunarSky (sun_from_earth_enu,
   * moon_from_earth_enu_km, sun_distance_from_earth_km, earth_axes_enu, eclipse_ring_factor,
   * dark_side_exposure).
   */
  drawTelescopicEarth(view, earth, sky) {
    const { cw, ch, right: camRight, camUp } = view;
    const { ex, ey } = earth;
    const rEarth = Math.max(6.5, earth.rExact);
    const pad = Math.max(4.0, rEarth * 0.14);
    const rOuter = rEarth + pad;

    const x0 = Math.max(0.0, ex - rOuter);
    const x1 = Math.min(cw, ex + rOuter + 1.0);
    const y0 = Math.max(0.0, ey - rOuter);
    const y1 = Math.min(ch, ey + rOuter + 1.0);
    if (x1 <= x0 || y1 <= y0) return;

    const eZ = earth.dirEnu.map((v) => -v);
    let eX = camRight.map((v, i) => v - dot3(camRight, eZ) * eZ[i]);
    let nxNorm = norm3(eX);
    if (nxNorm < 1e-6) {
      eX = cross3(camUp, eZ).map((v) => -v);
      nxNorm = norm3(eX);
    }
    eX = eX.map((v) => v / nxNorm);

    let eY = camUp.map((v, i) => v - dot3(camUp, eZ) * eZ[i]);
    const dYX = dot3(eY, eX);
    eY = eY.map((v, i) => v - dYX * eX[i]);
    let nyNorm = norm3(eY);
    if (nyNorm < 1e-6) {
      eY = cross3(eZ, eX).map((v) => -v);
      nyNorm = norm3(eY);
    }
    eY = eY.map((v) => v / nyNorm);

    const [xEcef, yEcef, zEcef] = sky.earth_axes_enu;
    const texelsPerPx = this.nightBaseW / Math.max(1.0, 2.0 * Math.PI * rEarth);
    const nightLod = Math.min(Math.max(Math.log2(Math.max(1.0, texelsPerPx)), 0.0), this.nightMaxMip);

    const { gl } = this;
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texEarthDay);
    gl.activeTexture(gl.TEXTURE0 + 1);
    gl.bindTexture(gl.TEXTURE_2D, this.texEarthNight);
    gl.activeTexture(gl.TEXTURE0 + 2);
    gl.bindTexture(gl.TEXTURE_2D, this.texEarthClouds);

    this._uploadScreenRect(x0, y0, x1, y1, cw, ch);
    gl.useProgram(this.progEarth.program);
    const u = this.progEarth.u;
    const sunE = sky.sun_from_earth_enu;
    const moonE = sky.moon_from_earth_enu_km;
    gl.uniform1f(u.u_ex, ex);
    gl.uniform1f(u.u_ey, ey);
    gl.uniform1f(u.u_r_earth, rEarth);
    gl.uniform1f(u.u_ch, ch);
    gl.uniform3f(u.u_e_x_cam, eX[0], eX[1], eX[2]);
    gl.uniform3f(u.u_e_y_cam, eY[0], eY[1], eY[2]);
    gl.uniform3f(u.u_e_z_cam, eZ[0], eZ[1], eZ[2]);
    gl.uniform3f(u.u_x_ecef, xEcef[0], xEcef[1], xEcef[2]);
    gl.uniform3f(u.u_y_ecef, yEcef[0], yEcef[1], yEcef[2]);
    gl.uniform3f(u.u_z_ecef, zEcef[0], zEcef[1], zEcef[2]);
    gl.uniform3f(u.u_sun_from_earth_enu, sunE[0], sunE[1], sunE[2]);
    gl.uniform3f(u.u_moon_from_earth_enu, moonE[0], moonE[1], moonE[2]);
    gl.uniform1f(u.u_moon_sun_dot, dot3(moonE, sunE));
    gl.uniform1f(u.u_sun_dist_km, sky.sun_distance_from_earth_km);
    gl.uniform1f(u.u_cloud_offset, earth.cloudOffset);
    gl.uniform1f(u.u_eclipse_ring_factor, sky.eclipse_ring_factor);
    gl.uniform1f(u.u_dark_side_exposure, sky.dark_side_exposure);
    gl.uniform1i(u.u_has_day, this.hasDay ? 1 : 0);
    gl.uniform1i(u.u_has_night, this.hasNight ? 1 : 0);
    gl.uniform1i(u.u_has_clouds, this.hasClouds ? 1 : 0);
    gl.uniform1f(u.u_night_lod, nightLod);
    gl.uniform1i(u.u_tex_day, 0);
    gl.uniform1i(u.u_tex_night, 1);
    gl.uniform1i(u.u_tex_clouds, 2);

    gl.bindVertexArray(this.vaoEarth);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);
  }
}
