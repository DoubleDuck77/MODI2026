// Port OrbitCamera i draw_runs z neworb.py:584-656 — kamera krążąca wokół środka Księżyca
// i rysowanie odcinków tylko między kolejnymi widocznymi punktami. Układ: związany z Księżycem, km.

export const R_MOON = 1737.4;

const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => Math.hypot(a[0], a[1], a[2]);

export function latlonToXyz(latDeg, lonDeg, radius = R_MOON) {
  const lat = (latDeg * Math.PI) / 180;
  const lon = (lonDeg * Math.PI) / 180;
  const cl = Math.cos(lat);
  return [radius * cl * Math.cos(lon), radius * cl * Math.sin(lon), radius * Math.sin(lat)];
}

export function xyzToLatlon(v) {
  const r = Math.max(norm(v), 1e-12);
  return [
    (Math.asin(Math.max(-1, Math.min(1, v[2] / r))) * 180) / Math.PI,
    (Math.atan2(v[1], v[0]) * 180) / Math.PI,
  ];
}

export class OrbitCamera {
  static MIN_DIST = R_MOON * 1.35;
  static MAX_DIST = 300000.0;

  constructor(latDeg = 15.0, lonDeg = 0.0, dist = 6000.0) {
    this.dist = dist;
    this.setView(latDeg, lonDeg);
  }

  setView(latDeg, lonDeg) {
    this.lat = Math.max(-89.5, Math.min(89.5, Number(latDeg)));
    this.lon = ((((Number(lonDeg) + 180.0) % 360.0) + 360.0) % 360.0) - 180.0;
    const lat = (this.lat * Math.PI) / 180;
    const lon = (this.lon * Math.PI) / 180;
    this.c = [Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)];
    const fwd = [-this.c[0], -this.c[1], -this.c[2]];
    const right = cross(fwd, [0, 0, 1]);
    const rn = norm(right);
    this.right = right.map((x) => x / rn);
    this.up = cross(this.right, fwd);
  }

  zoom(factor) {
    this.dist = Math.max(OrbitCamera.MIN_DIST, Math.min(OrbitCamera.MAX_DIST, this.dist * factor));
  }

  /** pts: płaska tablica [x, y, z, (t)] co `stride`; zwraca {sx, sy, depth}. */
  project(pts, cx, cy, focal, stride = 3) {
    const n = Math.floor(pts.length / stride);
    const sx = new Float64Array(n);
    const sy = new Float64Array(n);
    const depth = new Float64Array(n);
    const { c, right, up, dist } = this;
    for (let i = 0; i < n; i++) {
      const x = pts[i * stride];
      const y = pts[i * stride + 1];
      const z = pts[i * stride + 2];
      const d = dist - (x * c[0] + y * c[1] + z * c[2]);
      const safe = d > 1.0 ? d : 1.0;
      sx[i] = cx + ((x * right[0] + y * right[1] + z * right[2]) * focal) / safe;
      sy[i] = cy - ((x * up[0] + y * up[1] + z * up[2]) * focal) / safe;
      depth[i] = d;
    }
    return { sx, sy, depth };
  }

  /** Widoczność: przed kamerą i nie za tarczą Księżyca (neworb.py:618-626). */
  visible(pts, stride = 3) {
    const n = Math.floor(pts.length / stride);
    const ok = new Uint8Array(n);
    const cam = this.c.map((v) => v * this.dist);
    const R2 = R_MOON * R_MOON * (1.0 - 1e-9);
    for (let i = 0; i < n; i++) {
      const px = pts[i * stride];
      const py = pts[i * stride + 1];
      const pz = pts[i * stride + 2];
      const vx = px - cam[0];
      const vy = py - cam[1];
      const vz = pz - cam[2];
      const vv = vx * vx + vy * vy + vz * vz;
      const s = -(vx * cam[0] + vy * cam[1] + vz * cam[2]) / Math.max(vv, 1e-12);
      const qx = cam[0] + s * vx;
      const qy = cam[1] + s * vy;
      const qz = cam[2] + s * vz;
      const hidden = s > 0.0 && s < 1.0 && qx * qx + qy * qy + qz * qz < R2;
      ok[i] = this.dist - (px * this.c[0] + py * this.c[1] + pz * this.c[2]) > 1.0 && !hidden ? 1 : 0;
    }
    return ok;
  }

  apparentRadius(focal) {
    const D = this.dist;
    return (focal * R_MOON) / Math.sqrt(D * D - R_MOON * R_MOON);
  }
}

/** draw_runs: linie tylko między sąsiednimi punktami ok (i bez cięcia). */
export function drawRuns(ctx, color, xs, ys, ok, cut = null, width = 1) {
  const n = xs.length;
  if (n < 2) return;
  const good = (i) => ok[i] && Math.abs(xs[i]) < 1e5 && Math.abs(ys[i]) < 1e5;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  let open = false;
  for (let i = 0; i < n - 1; i++) {
    const link = good(i) && good(i + 1) && !(cut && cut[i]);
    if (link) {
      if (!open) { ctx.moveTo(xs[i], ys[i]); open = true; }
      ctx.lineTo(xs[i + 1], ys[i + 1]);
    } else {
      open = false;
    }
  }
  ctx.stroke();
}

