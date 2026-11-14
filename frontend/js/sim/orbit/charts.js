// Port draw_chart (neworb.py:1486-1518): wykres historii z zakresem min/max i podpisami.
import { FONT_BOLD, FONT_SMALL, fmtComma, rgb, roundRect, text } from './draw2d.js';

export function drawChart(ctx, title, values, x, y, w, h, lineColor, unit) {
  text(ctx, title, [180, 200, 220], x, y, FONT_BOLD);
  const rect = { x, y: y + 22, w, h };
  roundRect(ctx, [8, 10, 15], rect.x, rect.y, rect.w, rect.h, 4);
  roundRect(ctx, [45, 60, 80], rect.x + 0.5, rect.y + 0.5, rect.w - 1, rect.h - 1, 4, 1);
  if (values.length < 2) return;
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const loLabel = lo;
  const hiLabel = hi;
  if (hi - lo < 1e-9) { lo -= 0.5; hi += 0.5; }
  const pad = (hi - lo) * 0.08;
  lo -= pad;
  hi += pad;
  const bottom = rect.y + rect.h;
  ctx.beginPath();
  values.forEach((v, i) => {
    const px = rect.x + Math.trunc((i / (values.length - 1)) * (rect.w - 2)) + 1;
    const py = bottom - 1 - Math.trunc(((v - lo) / (hi - lo)) * (rect.h - 2));
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.strokeStyle = rgb(lineColor);
  ctx.lineWidth = 1;
  ctx.stroke();
  text(ctx, `${fmtComma(hiLabel, 3)} ${unit}`, [145, 155, 170], rect.x + 5, rect.y + 4, FONT_SMALL);
  text(ctx, `${fmtComma(loLabel, 3)} ${unit}`, [145, 155, 170], rect.x + 5, bottom - 17, FONT_SMALL);
}
