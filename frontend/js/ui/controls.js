// Kontrolki w nagłówku: czas, odtwarzanie, prędkość, widok, obserwator.

import { SIM_END, SIM_START } from '../core/clock.js';

const HOUR_MS = 3_600_000;
const toInputValue = (ms) => new Date(ms).toISOString().slice(0, 16); // datetime-local, interpretowane jako UTC

export function bindControls({ clock, observer, scene }) {
  const $ = (id) => document.getElementById(id);
  const timeInput = $('time-input');
  const slider = $('time-slider');
  const playBtn = $('play-btn');
  const speed = $('speed-select');
  const view = $('view-select');
  const lat = $('lat-input');
  const lon = $('lon-input');

  slider.min = String(SIM_START);
  slider.max = String(SIM_END);
  slider.step = String(HOUR_MS);
  timeInput.min = toInputValue(SIM_START);
  timeInput.max = toInputValue(SIM_END);

  let scheduled = false;
  const renderTime = () => {
    scheduled = false;
    timeInput.value = toInputValue(clock.t);
    slider.value = String(clock.t);
  };
  clock.addEventListener('timechange', () => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(renderTime);
    }
  });
  renderTime();

  timeInput.addEventListener('change', () => {
    const ms = Date.parse(`${timeInput.value}:00Z`);
    if (Number.isFinite(ms)) clock.seek(ms);
  });
  slider.addEventListener('input', () => clock.seek(Number(slider.value)));

  const renderPlay = () => {
    playBtn.textContent = clock.playing ? '❚❚ Pauza' : '▶ Play';
    playBtn.setAttribute('aria-pressed', String(clock.playing));
  };
  playBtn.addEventListener('click', () => clock.toggle());
  clock.addEventListener('playstatechange', renderPlay);
  renderPlay();

  speed.value = String(clock.speedHoursPerSecond);
  speed.addEventListener('change', () => { clock.speedHoursPerSecond = Number(speed.value); });

  view.value = scene.activeView;
  view.addEventListener('change', () => scene.setView(view.value));

  const renderObserver = () => {
    lat.value = String(observer.lat_deg);
    lon.value = String(observer.lon_deg);
  };
  const applyObserver = () => {
    observer.set(lat.value, lon.value);
    renderObserver();
  };
  lat.addEventListener('change', applyObserver);
  lon.addEventListener('change', applyObserver);
  renderObserver();

  document.addEventListener('keydown', (e) => {
    if (e.code !== 'Space' || e.target.closest('input, select, button, textarea')) return;
    e.preventDefault();
    clock.toggle();
  });
}
