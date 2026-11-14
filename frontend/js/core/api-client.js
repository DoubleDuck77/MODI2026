// Klient API. Ścieżki endpointów pochodzą z manifestu (/api/v1/features), nie są wpisywane ręcznie.

export class ApiError extends Error {
  constructor(status, detail, url) {
    super(`HTTP ${status} ${url}${detail ? `: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : ''}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export class ApiClient {
  #cache = new Map();

  constructor(baseUrl = '/api/v1') {
    this.baseUrl = baseUrl;
  }

  manifest() {
    return this.getJson(`${this.baseUrl}/features`);
  }

  /** `cache: true` dla endpointów static — każdy URL pobierany najwyżej raz. */
  getJson(path, params = {}, { signal, cache = false } = {}) {
    const url = new URL(path, window.location.origin);
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, v);
    }
    const key = url.toString();
    if (cache && this.#cache.has(key)) return this.#cache.get(key);
    const promise = this.#fetchJson(key, signal);
    if (cache) {
      this.#cache.set(key, promise);
      promise.catch(() => this.#cache.delete(key));
    }
    return promise;
  }

  frame({ t, lat_deg, lon_deg }, keys, { signal } = {}) {
    return this.getJson(`${this.baseUrl}/frame`, { t, lat_deg, lon_deg, keys: keys.join(',') }, { signal });
  }

  async #fetchJson(url, signal) {
    const res = await fetch(url, { signal, headers: { Accept: 'application/json' } });
    const text = await res.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = text; }
    if (!res.ok) throw new ApiError(res.status, body?.detail ?? body, url);
    return body;
  }
}
