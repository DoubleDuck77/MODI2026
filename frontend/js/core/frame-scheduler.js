// Planista zapytań /api/v1/frame: jedno zapytanie na wszystkie dane zależne od czasu.
// - seek / zmiana obserwatora → od razu,
// - tick (odtwarzanie) → nie częściej niż co minSimIntervalMs czasu symulacji
//   ORAZ co minRealIntervalMs czasu rzeczywistego (maks. ~4 zapytania/s przy każdej prędkości),
// - nowe zapytanie przerywa poprzednie, a spóźniona odpowiedź starszego jest odrzucana.

export class FrameScheduler {
  #seq = 0;
  #controller = null;
  #lastT = null;
  #lastReal = -Infinity;

  constructor({
    api, clock, observer, getActiveKeys, dispatch, onError,
    minSimIntervalMs = 3_600_000, minRealIntervalMs = 250, now = () => performance.now(),
  }) {
    Object.assign(this, { api, clock, observer, getActiveKeys, dispatch, onError, minSimIntervalMs, minRealIntervalMs, now });
  }

  start() {
    this.#lastT = this.clock.t;
    this.#lastReal = this.now();
    this.clock.addEventListener('timechange', (e) => {
      if (e.detail.reason !== 'tick') {
        this.refresh(e.detail.reason);
        return;
      }
      const simDue = Math.abs(this.clock.t - this.#lastT) >= this.minSimIntervalMs;
      const realDue = this.now() - this.#lastReal >= this.minRealIntervalMs;
      if (simDue && realDue) this.refresh('tick');
    });
    this.observer.addEventListener('observerchange', () => this.refresh('observer'));
  }

  async refresh(reason = 'manual') {
    const keys = this.getActiveKeys();
    if (!keys.length) return;

    this.#controller?.abort();
    const controller = new AbortController();
    this.#controller = controller;
    const seq = ++this.#seq;
    const t = this.clock.t;
    this.#lastT = t;
    this.#lastReal = this.now();

    const query = { t: new Date(t).toISOString(), lat_deg: this.observer.lat_deg, lon_deg: this.observer.lon_deg };
    let body;
    try {
      body = await this.api.frame(query, keys, { signal: controller.signal });
    } catch (err) {
      if (err?.name === 'AbortError' || seq !== this.#seq) return;
      const message = `frame (${reason}): ${err?.message ?? err}`;
      for (const key of keys) this.onError(key, message);
      return;
    }
    if (seq !== this.#seq) return; // spóźniona odpowiedź starszego zapytania

    for (const [key, payload] of Object.entries(body.payloads)) this.dispatch(key, payload);
    for (const [key, message] of Object.entries(body.errors)) this.onError(key, message);
  }
}
