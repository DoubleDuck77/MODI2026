// Wspólne prymitywy 2D odwzorowujące pygame.draw / font.render na canvas (piksele CSS).

export const FONT = '14px "DejaVu Sans Mono", ui-monospace, monospace';
export const FONT_SMALL = '12px "DejaVu Sans Mono", ui-monospace, monospace';
export const FONT_BOLD = 'bold 15px "DejaVu Sans Mono", ui-monospace, monospace';

export const rgb = (c, a = 1) => (a === 1 ? `rgb(${c[0]},${c[1]},${c[2]})` : `rgba(${c[0]},${c[1]},${c[2]},${a})`);

export function circle(ctx, color, x, y, r, width = 0) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 2 * Math.PI);
  if (width > 0) { ctx.strokeStyle = rgb(color); ctx.lineWidth = width; ctx.stroke(); } else { ctx.fillStyle = rgb(color); ctx.fill(); }
}

export function line(ctx, color, x0, y0, x1, y1, width = 1) {
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.strokeStyle = rgb(color);
  ctx.lineWidth = width;
  ctx.stroke();
}

export function roundRect(ctx, color, x, y, w, h, radius = 0, width = 0, alpha = 1) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, radius);
  if (width > 0) { ctx.strokeStyle = rgb(color, alpha); ctx.lineWidth = width; ctx.stroke(); } else { ctx.fillStyle = rgb(color, alpha); ctx.fill(); }
}

/** font.render + blit w lewym górnym rogu (x, y). */
export function text(ctx, str, color, x, y, font = FONT) {
  ctx.font = font;
  ctx.textBaseline = 'top';
  ctx.fillStyle = rgb(color);
  ctx.fillText(str, x, y);
}

export function textSize(ctx, str, font = FONT) {
  ctx.font = font;
  const m = ctx.measureText(str);
  return { w: Math.ceil(m.width), h: Math.ceil((m.fontBoundingBoxAscent ?? 12) + (m.fontBoundingBoxDescent ?? 4)) };
}

/** draw_sun_marker (neworb.py:884-891) */
export function drawSunMarker(ctx, x, y, size = 6) {
  for (let k = 0; k < 8; k++) {
    const a = (k * Math.PI) / 4;
    line(ctx, [255, 210, 60], x + Math.cos(a) * (size + 2), y + Math.sin(a) * (size + 2), x + Math.cos(a) * (size + 5), y + Math.sin(a) * (size + 5));
  }
  circle(ctx, [20, 16, 4], x, y, size + 1);
  circle(ctx, [255, 220, 70], x, y, size);
}

/** draw_earth_marker (neworb.py:894-897) */
export function drawEarthMarker(ctx, x, y, size = 6) {
  circle(ctx, [8, 12, 18], x, y, size + 2);
  circle(ctx, [70, 140, 255], x, y, size);
  circle(ctx, [200, 230, 255], x, y, size, 1);
}

/** Python: f"{v:,.Nf}" */
export const fmtComma = (v, d) => v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
/** Python: f"{v:+W.Nf}" */
export const fmtSigned = (v, d, w = 0) => ((v >= 0 ? '+' : '') + v.toFixed(d)).padStart(w);
/** Python: f"{v:W.Nf}" */
export const fmtWidth = (v, d, w) => v.toFixed(d).padStart(w);
