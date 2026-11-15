// Wykresy słupkowe „ROI kontra globalnie” — port radius.py:332-385 na canvas 2D.
// Kolory, tytuły, kolejność kategorii i etykiety słupków jak w matplotlibie (napisy po angielsku).

const FONT = '"DejaVu Sans", Arial, sans-serif';
const PT = 100 / 72; // 1 pt matplotlibu w pikselach przy 100 px/cal

/** Ładne podziałki osi (1, 2, 2.5, 5 × 10^n), podobnie do MaxNLocator. */
export function niceTicks(lo, hi, maxTicks = 8) {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / Math.max(1, maxTicks - 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}

export const fmtTick = (v) => String(+v.toPrecision(10));

/**
 * Rysuje jeden panel wykresu (jedna grupa z catalog.chart_groups).
 * rect = obszar osi {x, y, w, h} w px; opts = {radiusKm, legend, scale}.
 */
export function drawBarChart(ctx, group, rows, { rect, radiusKm = 0, legend = false, scale = 1 } = {}) {
  const { x, y, w, h } = rect;
  const k = PT * scale;
  const font = (pt, bold = false) => `${bold ? 'bold ' : ''}${(pt * k).toFixed(1)}px ${FONT}`;
  ctx.save();
  ctx.fillStyle = '#181c23'; // radius.py:337
  ctx.fillRect(x, y, w, h);
  const byKey = new Map(rows.map((r) => [r.resource_key, r]));
  const keys = group.keys.filter((key) => byKey.has(key));
  if (!keys.length) { ctx.restore(); return; }
  const roi = keys.map((key) => Number(byKey.get(key).roi_weighted_mean));
  const glb = keys.map((key) => Number(byKey.get(key).lunar_global_mean));
  const rel = keys.map((key) => Number(byKey.get(key).diff_vs_global_pct));
  const hi = Math.max(...roi, ...glb, 1e-6);
  const xMax = hi * 1.48;
  const px = (v) => x + (v / xMax) * w;
  // oś Y odwrócona; zakres jak autoskala matplotlibu (słupki od −0.35 do n−0.65, margines 5 %)
  const n = keys.length;
  const lo0 = -0.35;
  const hi0 = n - 1 + 0.35;
  const pad = 0.05 * (hi0 - lo0);
  const yMin = lo0 - pad;
  const yMax = hi0 + pad;
  const py = (v) => y + ((v - yMin) / (yMax - yMin)) * h;

  // siatka pionowa (radius.py:357) i podziałki osi X
  const ticks = niceTicks(0, xMax, 8);
  ctx.strokeStyle = '#30363d';
  ctx.lineWidth = 0.6 * PT;
  ctx.setLineDash([3.7 * PT * 0.6, 1.6 * PT * 0.6]);
  ctx.beginPath();
  for (const t of ticks) { ctx.moveTo(px(t), y); ctx.lineTo(px(t), y + h); }
  ctx.stroke();
  ctx.setLineDash([]);

  // słupki (radius.py:347-348)
  ctx.fillStyle = '#58a6ff';
  roi.forEach((v, i) => ctx.fillRect(x, py(i - 0.18 - 0.17), px(v) - x, py(i - 0.18 + 0.17) - py(i - 0.18 - 0.17)));
  ctx.fillStyle = '#6e7681';
  glb.forEach((v, i) => ctx.fillRect(x, py(i + 0.18 - 0.17), px(v) - x, py(i + 0.18 + 0.17) - py(i + 0.18 - 0.17)));

  // etykiety wartości (radius.py:374-385)
  ctx.font = font(7.6);
  ctx.fillStyle = '#d0d7de';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  keys.forEach((_, i) => {
    const xt = Math.max(roi[i], glb[i]) + 0.02 * hi;
    const sign = rel[i] >= 0 ? '+' : '-';
    ctx.fillText(`${roi[i].toFixed(2)} ${group.unit} (${sign}${Math.abs(rel[i]).toFixed(0)}%)`, px(xt), py(i));
  });

  // osie: lewa i dolna linia (#30363d), bez górnej i prawej
  ctx.strokeStyle = '#30363d';
  ctx.lineWidth = 0.8 * PT;
  ctx.beginPath();
  ctx.moveTo(x, y); ctx.lineTo(x, y + h); ctx.lineTo(x + w, y + h);
  ctx.stroke();

  // podziałki i podpisy: kategorie (pogrubione) i oś X
  ctx.fillStyle = '#e6edf3';
  ctx.font = font(8.5, true);
  ctx.textAlign = 'right';
  keys.forEach((key, i) => ctx.fillText(key, x - 7 * scale, py(i)));
  ctx.fillStyle = '#c9d1d9';
  ctx.font = font(7.5);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.strokeStyle = '#c9d1d9';
  ctx.lineWidth = 0.8 * PT;
  ctx.beginPath();
  for (const t of ticks) { ctx.moveTo(px(t), y + h); ctx.lineTo(px(t), y + h + 3.5 * k); }
  ctx.stroke();
  for (const t of ticks) ctx.fillText(fmtTick(t), px(t), y + h + 3.5 * k + 3 * scale);

  // tytuł po lewej nad osią (radius.py:361)
  ctx.fillStyle = '#ffffff';
  ctx.font = font(9.5, true);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(group.title, x, y - 5 * k);

  // legenda w prawym dolnym rogu pierwszego panelu (radius.py:387-393)
  if (legend) {
    const items = [[`ROI R=${radiusKm.toFixed(0)} km`, '#58a6ff'], ['Global Mean', '#6e7681']];
    ctx.font = font(7.8);
    const tw = Math.max(...items.map(([t]) => ctx.measureText(t).width));
    const rowH = 7.8 * k * 1.55;
    const bw = 8 * k + tw + 14 * k + 12 * scale;
    const bh = rowH * items.length + 8 * scale;
    const bx = x + w - bw - 6 * scale;
    const by = y + h - bh - 6 * scale;
    ctx.fillStyle = '#21262d';
    ctx.strokeStyle = '#30363d';
    ctx.lineWidth = 1;
    ctx.fillRect(bx, by, bw, bh);
    ctx.strokeRect(bx, by, bw, bh);
    ctx.textBaseline = 'middle';
    items.forEach(([t, c], i) => {
      const cy = by + 4 * scale + rowH * (i + 0.5);
      ctx.fillStyle = c;
      ctx.fillRect(bx + 6 * scale, cy - 3.5 * k, 10 * k, 7 * k);
      ctx.fillStyle = '#e6edf3';
      ctx.fillText(t, bx + 6 * scale + 10 * k + 5 * scale, cy);
    });
  }
  ctx.restore();
}

/** Układ dwóch paneli jak gridspec radius.py:216-226 (top .92, bottom .055, hspace .32, wysokości 8 : 2.6). */
export function chartRects(W, H) {
  const left = 0.18 * W; // miejsce na podpisy kategorii (w figurze: 0.625 z lewą kolumną)
  const right = 0.975 * W;
  const top = 0.08 * H;
  const bottom = 0.945 * H;
  const avg = (bottom - top) / 2.32;
  const gap = 0.32 * avg;
  const usable = bottom - top - gap;
  const h1 = (usable * 8) / 10.6;
  const h2 = usable - h1;
  return [
    { x: left, y: top, w: right - left, h: h1 },
    { x: left, y: top + h1 + gap, w: right - left, h: h2 },
  ];
}
