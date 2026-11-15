// Strona główna: wykresy „One month, two sites” z danymi z /api/wykresy (frontend/data/site-comparison-2026-12.json).
// Jedna oś Y na wykres (stopnie): wysokość ciała (linia) i horyzont terenu w jego azymucie (pole „ground”).

const DATA_URL = '/data/site-comparison-2026-12.json';
const SVG = 'http://www.w3.org/2000/svg';
const BODY = {
  sun: { key: 'sun_deg', terrain: 'sun_terrain_deg', name: 'Sun', range: 'sun_deg_range' },
  earth: { key: 'earth_deg', terrain: 'earth_terrain_deg', name: 'Earth', range: 'earth_deg_range' },
};
const PAD = { top: 8, right: 8, bottom: 22, left: 40 };

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function niceStep(span) {
  const raw = span / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const f = raw / mag;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
}

function yDomain(values) {
  let lo = Math.min(...values), hi = Math.max(...values);
  const step = niceStep(hi - lo || 1);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  return { lo, hi, step };
}

function fmtDeg(v) {
  return `${v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}°`;
}

function timeAt(t0, stepH, i) {
  const d = new Date(t0.replace(' ', 'T') + ':00Z');
  d.setUTCHours(d.getUTCHours() + i * stepH);
  return d;
}

function fmtTime(d) {
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC';
}

function draw(plot, data, siteKey, bodyKey) {
  const site = data.sites[siteKey];
  const body = BODY[bodyKey];
  const ys = site[body.key];
  const ts = site[body.terrain];
  const n = ys.length;
  const w = plot.clientWidth;
  const h = plot.clientHeight;
  if (!w || !h) return;

  plot.replaceChildren();
  const svg = el('svg', { width: w, height: h, viewBox: `0 0 ${w} ${h}`, role: 'img',
    'aria-label': `${body.name} altitude at site ${siteKey}, ${fmtDeg(site.stats[body.range][0])} to ${fmtDeg(site.stats[body.range][1])}, versus the terrain horizon, 1 to 30 December 2026` }, plot);

  const { lo, hi, step } = yDomain(ys.concat(ts));
  const iw = w - PAD.left - PAD.right;
  const ih = h - PAD.top - PAD.bottom;
  const x = (i) => PAD.left + (i / (n - 1)) * iw;
  const y = (v) => PAD.top + (1 - (v - lo) / (hi - lo)) * ih;

  const grid = el('g', { class: 'grid' }, svg);
  const decimals = step < 1 ? 1 : 0;
  for (let v = lo; v <= hi + 1e-9; v += step) {
    const yy = Math.round(y(v)) + 0.5;
    el('line', { x1: PAD.left, x2: w - PAD.right, y1: yy, y2: yy, class: Math.abs(v) < 1e-9 ? 'zero' : '' }, grid);
    const label = el('text', { x: PAD.left - 8, y: yy + 4, 'text-anchor': 'end', class: 'tick' }, svg);
    label.textContent = `${v < -1e-9 ? '−' : ''}${Math.abs(v).toFixed(decimals)}°`;
  }
  // Ticks on 1, 8, 15, 22, 29 December (indexes from step_h).
  for (const day of [1, 8, 15, 22, 29]) {
    const i = ((day - 1) * 24) / data.step_h;
    if (i > n - 1) continue;
    const label = el('text', { x: x(i), y: h - 4, 'text-anchor': i === 0 ? 'start' : 'middle', class: 'tick' }, svg);
    label.textContent = `${day} Dec`;
  }

  // Ground: from the bottom of the plot up to the terrain horizon.
  let ground = `M${x(0)} ${y(lo)}`;
  let edge = '';
  ts.forEach((v, i) => { ground += `L${x(i).toFixed(1)} ${y(v).toFixed(1)}`; edge += `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`; });
  ground += `L${x(n - 1)} ${y(lo)}Z`;
  el('path', { d: ground, class: 'ground' }, svg);
  el('path', { d: edge, class: 'ground-edge' }, svg);

  let line = '';
  ys.forEach((v, i) => { line += `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`; });
  el('path', { d: line, class: `body ${bodyKey}` }, svg);

  // Hover layer: crosshair + tooltip.
  const cross = el('line', { y1: PAD.top, y2: PAD.top + ih, class: 'cross', visibility: 'hidden' }, svg);
  const dot = el('circle', { r: 4.5, class: `dot ${bodyKey}`, visibility: 'hidden' }, svg);
  const tip = document.createElement('div');
  tip.className = 'tooltip';
  tip.hidden = true;
  plot.appendChild(tip);

  const show = (clientX) => {
    const r = svg.getBoundingClientRect();
    const px = Math.min(Math.max(clientX - r.left, PAD.left), PAD.left + iw);
    const i = Math.round(((px - PAD.left) / iw) * (n - 1));
    const xx = x(i);
    cross.setAttribute('x1', xx); cross.setAttribute('x2', xx); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', xx); dot.setAttribute('cy', y(ys[i])); dot.setAttribute('visibility', 'visible');
    const visible = ys[i] > ts[i];
    tip.innerHTML = `<strong>${fmtTime(timeAt(data.t0, data.step_h, i))}</strong>`
      + `${body.name} ${fmtDeg(ys[i])}<br><span class="muted">Terrain ${fmtDeg(ts[i])}</span><br>`
      + (visible ? 'In view' : `<span class="muted">Hidden behind ${ys[i] < 0 ? 'the horizon' : 'the terrain'}</span>`);
    tip.hidden = false;
    const tw = tip.offsetWidth;
    tip.style.left = `${xx + 12 + tw > w ? xx - 12 - tw : xx + 12}px`;
  };
  const hide = () => { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); tip.hidden = true; };
  svg.addEventListener('pointermove', (e) => show(e.clientX));
  svg.addEventListener('pointerdown', (e) => show(e.clientX));
  svg.addEventListener('pointerleave', hide);
}

async function main() {
  const charts = [...document.querySelectorAll('.chart')];
  if (!charts.length) return;
  let data;
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    for (const c of charts) {
      c.querySelector('.plot').innerHTML = '<p class="msg">Chart data did not load. The numbers in the table above are the same results.</p>';
    }
    console.warn('[landing] chart data:', err);
    return;
  }
  const render = () => charts.forEach((c) => draw(c.querySelector('.plot'), data, c.dataset.site, c.dataset.body));
  render();
  let raf = 0;
  new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(render); })
    .observe(document.getElementById('charts'));
}

main();
