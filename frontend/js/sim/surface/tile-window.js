// Tekstura-okno z kafli 11.25° wokół obserwatora (odchylenie 1 z planu): zamiast globalnych
// tekstur DEM (66 MB) i albedo (100 MB) z LunarTerrain3D._init_gpu (geografia.py:1625-1662)
// GPU dostaje tylko kafle w promieniu r_max (+4 teksele DEM). Teren dalej leży pod
// geometrycznym horyzontem.

const R_MOON = 1737.4;                     // geografia.py:13
const MARGIN_RAD = (4 * Math.PI) / 2880;   // 4 teksele DEM zapasu (DEM ma 2880 wierszy)
const TILE_CACHE_MAX = 160;
const DEG = Math.PI / 180;

/** Wspólny LRU url → ArrayBuffer: powrót w znane miejsce nie pobiera kafli ponownie. */
const tileCache = new Map();

function cacheGet(url) {
  const buf = tileCache.get(url);
  if (buf) {
    tileCache.delete(url);
    tileCache.set(url, buf);
  }
  return buf;
}

function cachePut(url, buf) {
  tileCache.set(url, buf);
  while (tileCache.size > TILE_CACHE_MAX) tileCache.delete(tileCache.keys().next().value);
}

/** AbortSignal przerywany, gdy przerwie się którykolwiek z sygnałów. */
function anySignal(signals) {
  if (typeof AbortSignal.any === 'function') return AbortSignal.any(signals);
  const ctrl = new AbortController();
  for (const s of signals) {
    if (s.aborted) { ctrl.abort(s.reason); break; }
    s.addEventListener('abort', () => ctrl.abort(s.reason), { once: true });
  }
  return ctrl.signal;
}

async function fetchTile(url, signal, byteLength) {
  const hit = cacheGet(url);
  if (hit) return hit;
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  const buf = await res.arrayBuffer();
  if (buf.byteLength !== byteLength) throw new Error(`Kafel ${url}: ${buf.byteLength} B zamiast ${byteLength} B`);
  cachePut(url, buf);
  return buf;
}

export class TileWindow {
  /**
   * @param {WebGL2RenderingContext} gl
   * @param {{width:number,height:number,tile_w:number,tile_h:number,nx:number,ny:number,channels:number,url_template:string}} tileset
   *   TileSetInfo z lunar_surface.catalog
   * @param {{internalFormat:number, format:number, type:number, mipmaps?:boolean, unit?:number, rMoonKm?:number}} opts
   */
  constructor(gl, tileset, { internalFormat, format, type, mipmaps = false, unit = 0, rMoonKm = R_MOON }) {
    this.gl = gl;
    this.tileset = tileset;
    this.internalFormat = internalFormat;
    this.format = format;
    this.type = type;
    this.mipmaps = mipmaps;
    this.unit = unit;
    this.rMoonKm = rMoonKm;
    this.tileDeg = 360 / tileset.nx;   // 11.25° w obu zbiorach
    this.ArrayType = type === gl.FLOAT ? Float32Array : Uint8Array;
    this.tileBytes = tileset.tile_w * tileset.tile_h * tileset.channels * this.ArrayType.BYTES_PER_ELEMENT;

    this.texture = gl.createTexture();
    this.ready = false;
    this.key = '';
    this.sel = null;
    this.width = 0;
    this.height = 0;
    this.loaded = 0;
    this.total = 0;
    this._gen = 0;
    this._abort = null;

    this._bind();
    // DEM: NEAREST (texelFetch, interpolacja w shaderze); albedo: jak _init_gpu (geografia.py:1643-1662)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mipmaps ? gl.LINEAR_MIPMAP_LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, mipmaps ? gl.LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  }

  _bind() {
    const { gl } = this;
    gl.activeTexture(gl.TEXTURE0 + this.unit);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
  }

  /** Zakres kafli pokrywający czaszę o promieniu θ = r_max/R + 4 teksele DEM wokół (lat, lon). */
  selectTiles(latDeg, lonDeg, rMaxKm) {
    const { nx, ny } = this.tileset;
    const T = this.tileDeg;
    const theta = rMaxKm / this.rMoonKm + MARGIN_RAD;
    const thetaDeg = theta / DEG;
    const latMin = latDeg - thetaDeg;
    const latMax = latDeg + thetaDeg;
    const fullRing = latMax >= 90 || latMin <= -90 || Math.sin(theta) >= Math.cos(latDeg * DEG);
    const dLon = fullRing ? 180 : Math.asin(Math.sin(theta) / Math.cos(latDeg * DEG)) / DEG;
    const clampTy = (v) => Math.max(0, Math.min(ny - 1, v));
    const ty0 = clampTy(Math.floor((90 - latMax) / T));
    const ty1 = clampTy(Math.floor((90 - latMin) / T));
    let tx0 = Math.floor((lonDeg - dLon + 180) / T);
    const tx1 = Math.floor((lonDeg + dLon + 180) / T);
    let nTx = tx1 - tx0 + 1;
    if (nTx >= nx || fullRing) { tx0 = 0; nTx = nx; }
    return { ty0, ty1, tx0, nTx, fullRing };
  }

  /**
   * Składa okno dla obserwatora. Nowsze wywołanie unieważnia starsze (licznik generacji i
   * przerwanie pobierania), tak samo przerwany `signal`.
   * @returns {Promise<boolean>} true — okno gotowe dla tego wywołania; false — zastąpione/przerwane
   */
  async ensure(latDeg, lonDeg, rMaxKm, signal) {
    const sel = this.selectTiles(latDeg, lonDeg, rMaxKm);
    const key = `${sel.ty0}:${sel.ty1}:${sel.tx0}:${sel.nTx}`;
    if (key === this.key && this.ready) return true;

    const gen = ++this._gen;
    this._abort?.abort();
    const ctrl = new AbortController();
    this._abort = ctrl;
    const sig = signal ? anySignal([signal, ctrl.signal]) : ctrl.signal;

    const { gl } = this;
    const { tile_w: tw, tile_h: th, nx, url_template: tpl } = this.tileset;
    const nTy = sel.ty1 - sel.ty0 + 1;
    const w = sel.nTx * tw;
    const h = nTy * th;
    this.ready = false;
    this.key = key;
    this.sel = sel;
    this._bind();
    if (w !== this.width || h !== this.height) {
      gl.texImage2D(gl.TEXTURE_2D, 0, this.internalFormat, w, h, 0, this.format, this.type, null);
      this.width = w;
      this.height = h;
    }
    // S = REPEAT tylko przy pełnym pierścieniu (okno obejmuje całą długość jak tekstura globalna)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, sel.nTx === nx ? gl.REPEAT : gl.CLAMP_TO_EDGE);

    this.loaded = 0;
    this.total = sel.nTx * nTy;
    const jobs = [];
    for (let row = 0; row < nTy; row++) {
      for (let i = 0; i < sel.nTx; i++) {
        const ty = sel.ty0 + row;
        const tx = (((sel.tx0 + i) % nx) + nx) % nx;
        const url = tpl.replace('{ty}', String(ty)).replace('{tx}', String(tx));
        jobs.push(fetchTile(url, sig, this.tileBytes).then((buf) => {
          if (gen !== this._gen) return;
          this._bind();
          gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
          gl.texSubImage2D(gl.TEXTURE_2D, 0, i * tw, row * th, tw, th, this.format, this.type, new this.ArrayType(buf));
          this.loaded++;
        }));
      }
    }
    try {
      await Promise.all(jobs);
    } catch (err) {
      if (gen === this._gen) ctrl.abort();
      if (gen !== this._gen || err?.name === 'AbortError') return false;
      throw err;
    }
    if (gen !== this._gen) return false;
    if (this.mipmaps) {
      this._bind();
      gl.generateMipmap(gl.TEXTURE_2D);
    }
    this.ready = true;
    return true;
  }

  /** Uniformy okna dla shadera: początek i rozmiar w tekselach globalnych, pełny pierścień. */
  uniforms() {
    const { tile_w: tw, tile_h: th, nx } = this.tileset;
    const s = this.sel;
    if (!s) return { origin: [0, 0], size: [1, 1], full: 0 };
    const tx0 = ((s.tx0 % nx) + nx) % nx;
    return {
      origin: [tx0 * tw, s.ty0 * th],
      size: [s.nTx * tw, (s.ty1 - s.ty0 + 1) * th],
      full: s.nTx === nx ? 1 : 0,
    };
  }

  /** Stan do root._debug.tiles. */
  info() {
    const s = this.sel;
    const nx = this.tileset.nx;
    return {
      ready: this.ready,
      loaded: this.loaded,
      total: this.total,
      ...(s ?? {}),
      tilesX: s ? Array.from({ length: s.nTx }, (_, i) => (((s.tx0 + i) % nx) + nx) % nx) : [],
      texSize: [this.width, this.height],
      ...this.uniforms(),
    };
  }
}
