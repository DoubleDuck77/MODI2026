// Zegar symulacji: jedyne źródło czasu dla całego frontu (ms od epoki, UTC).

export const SIM_START = Date.UTC(2000, 0, 1);
export const SIM_END = Date.UTC(2100, 0, 1);
const HOUR_MS = 3_600_000;

const clamp = (ms) => Math.min(SIM_END, Math.max(SIM_START, ms));

export class SimulationClock extends EventTarget {
  #t;
  #playing = false;

  constructor({ t = Date.UTC(2026, 0, 1), speedHoursPerSecond = 1 } = {}) {
    super();
    this.#t = clamp(t);
    this.speedHoursPerSecond = speedHoursPerSecond;
  }

  get t() { return this.#t; }
  get playing() { return this.#playing; }

  play() {
    if (this.#playing || this.#t >= SIM_END) return;
    this.#playing = true;
    this.dispatchEvent(new Event('playstatechange'));
  }

  pause() {
    if (!this.#playing) return;
    this.#playing = false;
    this.dispatchEvent(new Event('playstatechange'));
  }

  toggle() { this.#playing ? this.pause() : this.play(); }

  seek(ms) {
    if (!Number.isFinite(ms)) return;
    this.#t = clamp(ms);
    this.#emit('seek');
  }

  tick(dtSeconds) {
    if (!this.#playing || !(dtSeconds > 0)) return;
    this.#t = clamp(this.#t + dtSeconds * this.speedHoursPerSecond * HOUR_MS);
    this.#emit('tick');
    if (this.#t >= SIM_END) this.pause();
  }

  #emit(reason) {
    this.dispatchEvent(new CustomEvent('timechange', { detail: { t: this.#t, reason } }));
  }
}
