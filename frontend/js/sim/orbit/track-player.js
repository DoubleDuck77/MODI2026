// Odtwarzanie paczek z lunar_orbit.propagate + emulacja TrackBuffer z neworb.py.
// Czas: sekundy od epoki symulacji (jak time_elapsed w neworb.main).

const TRACK_CAPACITY = 20000;                        // TrackBuffer(20000), neworb.py:1138
const SAMPLE_COS = Math.cos((0.5 * Math.PI) / 180);  // neworb.SAMPLE_COS
const SAMPLE_MAX_DT = 600.0;                         // neworb.SAMPLE_MAX_DT
const MAX_STEP = 2.0;                                // neworb.MAX_STEP

const lerp = (a, b, f) => a + (b - a) * f;
const lerp3 = (a, b, f) => [lerp(a[0], b[0], f), lerp(a[1], b[1], f), lerp(a[2], b[2], f)];

export class TrackPlayer {
  constructor() {
    this.samples = [];
    this.status = 'ok';
    this.statusMessage = null;
    this.track = new Float64Array(TRACK_CAPACITY * 4);
    this.count = 0;
    this.head = 0;
    this.last = [0, 0, 0, 0];
    this.histT = 0;
  }

  /** set_state (neworb.py:1166-1178): czyści bufor, pierwszy punkt toru w t = 0. */
  reset(state) {
    this.samples = [];
    this.status = 'ok';
    this.statusMessage = null;
    this.count = 0;
    this.head = 0;
    const p = state.pos_km;
    this._push(p[0], p[1], p[2], 0);
    this.last = [p[0], p[1], p[2], 0];
    this.histT = 0;
  }

  /** Dokleja odpowiedź propagate wysłaną dla czasu startu startT (s od epoki). */
  append(track, startT) {
    const n = track.t_offset_s.length;
    for (let i = 0; i < n; i++) {
      const t = startT + track.t_offset_s[i];
      if (this.samples.length && t <= this.samples[this.samples.length - 1].t + 1e-9) continue;
      this.samples.push({
        t,
        pos: track.pos_km[i], vel: track.vel_kms[i], sun: track.sun_body_km[i], earth: track.earth_body_km[i],
        hp: track.periapsis_km[i], ha: track.apoapsis_km[i], ecc: track.eccentricity[i],
        dgR: track.mascon_dg_radial_mgal[i], dgH: track.mascon_dg_horiz_mgal[i], nearest: track.nearest_mascon[i],
      });
    }
    this.status = track.status;
    this.statusMessage = track.status_message;
  }

  get bufferedUntil() {
    return this.samples.length ? this.samples[this.samples.length - 1].t : -Infinity;
  }

  get bufferedFrom() {
    return this.samples.length ? this.samples[0].t : Infinity;
  }

  lastSampleAtOrBefore(t) {
    let best = null;
    for (const s of this.samples) { if (s.t <= t + 1e-9) best = s; else break; }
    return best;
  }

  truncateAfter(t) {
    this.samples = this.samples.filter((s) => s.t <= t + 1e-9);
    this.status = 'ok';
    this.statusMessage = null;
  }

  _segment(t) {
    const S = this.samples;
    let lo = 0;
    let hi = S.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (S[mid].t <= t) lo = mid; else hi = mid;
    }
    return [S[lo], S[hi]];
  }

  /** Stan w chwili t: pozycja/prędkość Hermite (pos + vel), reszta liniowo. */
  sampleAt(t) {
    const S = this.samples;
    if (!S.length) return null;
    if (S.length === 1 || t <= S[0].t) return { ...S[0], t: S[0].t };
    const lastS = S[S.length - 1];
    if (t >= lastS.t) return { ...lastS, t: lastS.t };
    const [a, b] = this._segment(t);
    const h = b.t - a.t;
    const s = (t - a.t) / h;
    const s2 = s * s;
    const s3 = s2 * s;
    const h00 = 2 * s3 - 3 * s2 + 1;
    const h10 = s3 - 2 * s2 + s;
    const h01 = -2 * s3 + 3 * s2;
    const h11 = s3 - s2;
    const d00 = 6 * s2 - 6 * s;
    const d10 = 3 * s2 - 4 * s + 1;
    const d01 = -6 * s2 + 6 * s;
    const d11 = 3 * s2 - 2 * s;
    const pos = [0, 1, 2].map((k) => h00 * a.pos[k] + h10 * h * a.vel[k] + h01 * b.pos[k] + h11 * h * b.vel[k]);
    const vel = [0, 1, 2].map((k) => (d00 * a.pos[k] + d10 * h * a.vel[k] + d01 * b.pos[k] + d11 * h * b.vel[k]) / h);
    return {
      t, pos, vel,
      sun: lerp3(a.sun, b.sun, s), earth: lerp3(a.earth, b.earth, s),
      hp: lerp(a.hp, b.hp, s),
      ha: a.ha == null || b.ha == null ? null : lerp(a.ha, b.ha, s),
      ecc: lerp(a.ecc, b.ecc, s),
      dgR: lerp(a.dgR, b.dgR, s), dgH: lerp(a.dgH, b.dgH, s),
      nearest: s < 0.5 ? a.nearest : b.nearest,
    };
  }

  /**
   * Dokłada punkty toru dla odcinka (histT, t] tak jak propagate w jednej klatce pygame:
   * n = ceil(Δ / MAX_STEP) kroków, reguła próbkowania sprawdzana po każdym kroku.
   */
  advanceHistory(t, rMoon, rEscape) {
    const dtAll = t - this.histT;
    if (dtAll <= 0) return;
    const n = Math.max(1, Math.ceil(dtAll / MAX_STEP));
    const step = dtAll / n;
    for (let k = 1; k <= n; k++) {
      const tk = this.histT + k * step;
      const st = this.sampleAt(tk);
      if (!st) break;
      const [x, y, z] = st.pos;
      const r = Math.hypot(x, y, z);
      const [lx, ly, lz, lt] = this.last;
      const lr = Math.hypot(lx, ly, lz);
      const cosAng = lr > 0 ? (x * lx + y * ly + z * lz) / (r * lr) : -1;
      const done = r <= rMoon || r > rEscape;
      if (done || cosAng < SAMPLE_COS || Math.abs(r - lr) > 0.01 * lr || tk - lt >= SAMPLE_MAX_DT) {
        this._push(x, y, z, tk);
        this.last = [x, y, z, tk];
      }
    }
    this.histT = t;
  }

  _push(x, y, z, t) {
    const o = this.head * 4;
    this.track[o] = x; this.track[o + 1] = y; this.track[o + 2] = z; this.track[o + 3] = t;
    this.head = (this.head + 1) % TRACK_CAPACITY;
    this.count = Math.min(TRACK_CAPACITY, this.count + 1);
  }

  /** TrackBuffer.view(): punkty w kolejności czasu, tablica [x, y, z, t] * count. */
  view() {
    if (this.count < TRACK_CAPACITY) return this.track.subarray(0, this.count * 4);
    const out = new Float64Array(TRACK_CAPACITY * 4);
    out.set(this.track.subarray(this.head * 4));
    out.set(this.track.subarray(0, this.head * 4), (TRACK_CAPACITY - this.head) * 4);
    return out;
  }
}
