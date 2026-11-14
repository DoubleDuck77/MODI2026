// Port GroundTrackMap (neworb.py:938-1036): mapa toru podsatelitarnego z nocną stroną, siatką,
// masconami, punktami orientacyjnymi, torem (cały przyciemniony + ostatni okres jasny) i markerami.
import { R_MOON, drawRuns, latlonToXyz, xyzToLatlon } from './orbit-camera.js';
import { FONT_SMALL, circle, drawEarthMarker, drawSunMarker, line, rgb, text, textSize } from './draw2d.js';

export class GroundTrackMap {
  constructor(levels) {
    this.levels = levels;   // [{tex, w, h, canvas}] z moon-render (największy pierwszy)
    this.size = null;
    this.base = null;
    this.normals = null;
    this.sun = null;
    this.canvas = document.createElement('canvas');
    this.valid = false;
  }

  _ensure(w, h) {
    if (this.size && this.size[0] === w && this.size[1] === h) return;
    this.size = [w, h];
    const tmp = document.createElement('canvas');
    tmp.width = w;
    tmp.height = h;
    const tctx = tmp.getContext('2d');
    if (this.levels) {
      const src = [...this.levels].reverse().find((l) => l.w >= w) ?? this.levels[0];
      tctx.imageSmoothingQuality = 'high';
      tctx.drawImage(src.tex.image, 0, 0, w, h);
      this.base = tctx.getImageData(0, 0, w, h).data;
    } else {
      this.base = new Uint8ClampedArray(w * h * 4).fill(95);
    }
    this.normals = new Float32Array(w * h * 3);
    for (let j = 0; j < h; j++) {
      const lat = 90.0 - ((j + 0.5) / h) * 180.0;
      for (let i = 0; i < w; i++) {
        const lon = ((i + 0.5) / w) * 360.0 - 180.0;
        const n = latlonToXyz(lat, lon, 1.0);
        this.normals.set(n, (j * w + i) * 3);
      }
    }
    this.canvas.width = w;
    this.canvas.height = h;
    this.sun = null;
    this.valid = false;
  }

  surface(w, h, sunDir) {
    this._ensure(w, h);
    if (this.valid) {
      if (!sunDir && !this.sun) return this.canvas;
      if (sunDir && this.sun && sunDir[0] * this.sun[0] + sunDir[1] * this.sun[1] + sunDir[2] * this.sun[2] > Math.cos((0.25 * Math.PI) / 180)) {
        return this.canvas;
      }
    }
    const img = new ImageData(w, h);
    const out = img.data;
    for (let p = 0; p < w * h; p++) {
      let f = 1;
      if (sunDir) {
        const n = p * 3;
        const day = Math.min(1, Math.max(0, (this.normals[n] * sunDir[0] + this.normals[n + 1] * sunDir[1] + this.normals[n + 2] * sunDir[2]) * 8.0 + 0.5));
        f = 0.35 + 0.65 * day;
      }
      for (let k = 0; k < 3; k++) out[p * 4 + k] = Math.trunc(Math.min(255, Math.max(0, this.base[p * 4 + k] * f)));
      out[p * 4 + 3] = 255;
    }
    this.canvas.getContext('2d').putImageData(img, 0, 0);
    this.sun = sunDir ? [...sunDir] : null;
    this.valid = true;
    return this.canvas;
  }

  static toXY(rect, lat, lon) {
    return [rect.x + ((lon + 180.0) / 360.0) * rect.w, rect.y + ((90.0 - lat) / 180.0) * rect.h];
  }

  draw(ctx, rect, track, tNow, recentWindow, pos, sunDir, subsolar, subearth, catalog, showMascons = true) {
    ctx.drawImage(this.surface(rect.w, rect.h, sunDir), rect.x, rect.y);
    ctx.save();
    ctx.beginPath();
    ctx.rect(rect.x, rect.y, rect.w, rect.h);
    ctx.clip();
    const grid = [70, 105, 125];
    for (let lon = -150; lon < 180; lon += 30) {
      const x = rect.x + ((lon + 180) / 360.0) * rect.w;
      line(ctx, grid, x, rect.y, x, rect.y + rect.h);
    }
    for (let lat = -60; lat < 90; lat += 30) {
      const y = rect.y + ((90 - lat) / 180.0) * rect.h;
      line(ctx, grid, rect.x, y, rect.x + rect.w, y);
    }
    if (showMascons) {
      for (const m of catalog.mascons) {
        const [mx, my] = GroundTrackMap.toXY(rect, m.lat_deg, m.lon_deg);
        const rx = Math.max(3, Math.trunc((((m.core_radius_km / R_MOON) * 180) / Math.PI / 360.0) * rect.w));
        circle(ctx, [255, 110, 145], Math.trunc(mx), Math.trunc(my), rx, 1);
      }
    }
    for (const lm of catalog.landmarks) {
      const [lx, ly] = GroundTrackMap.toXY(rect, lm.lat_deg, lm.lon_deg);
      circle(ctx, lm.color_rgb, Math.trunc(lx), Math.trunc(ly), 2);
    }
    const n = track.length / 4;
    if (n >= 2) {
      const xs = new Float64Array(n);
      const ys = new Float64Array(n);
      const lons = new Float64Array(n);
      const recent = new Uint8Array(n);
      for (let i = 0; i < n; i++) {
        const [lat, lon] = xyzToLatlon([track[i * 4], track[i * 4 + 1], track[i * 4 + 2]]);
        [xs[i], ys[i]] = GroundTrackMap.toXY(rect, lat, lon);
        lons[i] = lon;
        recent[i] = track[i * 4 + 3] >= tNow - recentWindow ? 1 : 0;
      }
      const cuts = new Uint8Array(n - 1);
      for (let i = 0; i < n - 1; i++) cuts[i] = Math.abs(lons[i + 1] - lons[i]) > 180.0 ? 1 : 0;
      drawRuns(ctx, rgb([150, 110, 60]), xs, ys, new Uint8Array(n).fill(1), cuts);
      drawRuns(ctx, rgb([255, 170, 60]), xs, ys, recent, cuts, 2);
    }
    for (const [point, marker] of [[subsolar, drawSunMarker], [subearth, drawEarthMarker]]) {
      if (point) {
        const [px, py] = GroundTrackMap.toXY(rect, point[0], point[1]);
        marker(ctx, Math.trunc(px), Math.trunc(py), 5);
      }
    }
    const [lat, lon] = xyzToLatlon(pos);
    const [px, py] = GroundTrackMap.toXY(rect, lat, lon);
    circle(ctx, [10, 10, 10], Math.trunc(px), Math.trunc(py), 6);
    circle(ctx, [255, 230, 90], Math.trunc(px), Math.trunc(py), 5);
    circle(ctx, [255, 80, 60], Math.trunc(px), Math.trunc(py), 2);
    ctx.restore();

    ctx.strokeStyle = rgb([45, 60, 80]);
    ctx.lineWidth = 1;
    ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, rect.w - 1, rect.h - 1);
    for (const lonL of [-180, -90, 0, 90, 180]) {
      const s = lonL ? (lonL > 0 ? `+${lonL}` : `${lonL}`) : '0';
      const { w } = textSize(ctx, s, FONT_SMALL);
      let x = rect.x + ((lonL + 180) / 360.0) * rect.w - w / 2;
      x = Math.min(Math.max(x, rect.x), rect.x + rect.w - w);
      text(ctx, s, [125, 140, 160], x, rect.y + rect.h + 2, FONT_SMALL);
    }
  }
}
