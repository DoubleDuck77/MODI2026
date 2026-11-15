// Strona /sim.html: manifest → wspólny zegar → leniwie tworzone tryby (Powierzchnia / Orbita / Zasoby).
// Tylko aktywny tryb ma pętlę rysowania i klawiaturę; tryb zapamiętany w location.hash.

import { ApiClient } from '/js/core/api-client.js';
import { SIM_END, SIM_START, SimulationClock } from '/js/core/clock.js';

const MODES = {
  surface: () => import('./surface/surface-mode.js').then((m) => m.createSurfaceMode),
  orbit: () => import('./orbit/orbit-mode.js').then((m) => m.createOrbitMode),
  resources: () => import('./resources/resources-mode.js').then((m) => m.createResourcesMode),
};
const toInputValue = (ms) => new Date(ms).toISOString().slice(0, 16); // datetime-local jako UTC

function showError(message) {
  const el = document.getElementById('sim-error');
  el.textContent = message;
  el.hidden = false;
}

function bindHeader(clock) {
  const timeInput = document.getElementById('sim-time-input');
  const playBtn = document.getElementById('sim-play-btn');
  timeInput.min = toInputValue(SIM_START);
  timeInput.max = toInputValue(SIM_END);
  let scheduled = false;
  const renderTime = () => {
    scheduled = false;
    if (document.activeElement !== timeInput) timeInput.value = toInputValue(clock.t);
  };
  clock.addEventListener('timechange', () => {
    if (!scheduled) { scheduled = true; requestAnimationFrame(renderTime); }
  });
  renderTime();
  timeInput.addEventListener('change', () => {
    const ms = Date.parse(`${timeInput.value}:00Z`);
    if (Number.isFinite(ms)) clock.seek(ms);
  });
  const renderPlay = () => {
    playBtn.textContent = clock.playing ? '❚❚ Pause' : '▶ Play';
    playBtn.setAttribute('aria-pressed', String(clock.playing));
  };
  playBtn.addEventListener('click', () => clock.toggle());
  clock.addEventListener('playstatechange', renderPlay);
  renderPlay();
}

async function bootstrap() {
  const api = new ApiClient('/api/v1');
  let manifest;
  try {
    manifest = await api.manifest();
  } catch (err) {
    showError(`Can't reach the API: ${err?.message ?? err}`);
    return;
  }
  const paths = new Map(manifest.features.flatMap((f) => f.endpoints.map((ep) => [ep.key, ep.path])));
  const endpoint = (key) => {
    const path = paths.get(key);
    if (!path) throw new Error(`Endpoint ${key} is missing from the manifest`);
    return path;
  };

  // Start: teraz zaokrąglone do minuty (jak domyślne --epoch w neworb.py:1095).
  const clock = new SimulationClock({ t: Math.floor(Date.now() / 60_000) * 60_000, speedHoursPerSecond: 24 });
  bindHeader(clock);

  const instances = new Map();
  let active = null;

  async function activate(name) {
    if (!MODES[name]) name = 'surface';
    if (active === name) return;
    if (active) instances.get(active)?.deactivate();
    for (const el of document.querySelectorAll('.sim-mode')) el.hidden = el.dataset.mode !== name;
    for (const btn of document.querySelectorAll('.mode-switch button')) {
      btn.setAttribute('aria-pressed', String(btn.dataset.mode === name));
    }
    active = name;
    if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
    try {
      if (!instances.has(name)) {
        const create = await MODES[name]();
        const root = document.getElementById(`mode-${name}-root`);
        instances.set(name, await create({ root, api, endpoint, clock }));
      }
      if (active === name) instances.get(name).activate();
    } catch (err) {
      console.error(err);
      showError(`Couldn't start ${name} mode: ${err?.message ?? err}`);
    }
  }

  for (const btn of document.querySelectorAll('.mode-switch button')) {
    btn.addEventListener('click', () => activate(btn.dataset.mode));
  }
  window.addEventListener('hashchange', () => activate(location.hash.slice(1)));
  await activate(location.hash.slice(1) || 'surface');

  window.modiSim = { api, clock, instances, manifest };
}

bootstrap();
