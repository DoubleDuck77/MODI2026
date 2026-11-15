// Inspektor kontraktów: ostatni payload każdego endpointu. Tekst JSON generowany tylko dla rozwiniętych wpisów.

const MAX_CHARS = 20_000;

export class Inspector {
  #entries = new Map();

  constructor(root) {
    this.root = root;
  }

  show(key, payload) {
    const entry = this.#entry(key);
    entry.details.classList.remove('is-error');
    entry.status.textContent = payload?.meta?.source ?? 'ok';
    entry.status.title = `Last updated: ${new Date().toLocaleTimeString('en-GB')}`;
    entry.pending = payload;
    if (entry.details.open) this.#render(entry);
  }

  error(key, message) {
    const entry = this.#entry(key);
    entry.details.classList.add('is-error');
    entry.status.textContent = 'error';
    entry.pending = null;
    entry.pre.textContent = message;
  }

  #render(entry) {
    if (entry.pending == null) return;
    let text = JSON.stringify(entry.pending, null, 2);
    if (text.length > MAX_CHARS) text = `${text.slice(0, MAX_CHARS)}\n… (truncated)`;
    entry.pre.textContent = text;
    entry.pending = null;
  }

  #entry(key) {
    let entry = this.#entries.get(key);
    if (entry) return entry;

    const details = document.createElement('details');
    details.className = 'inspector-entry';
    details.dataset.key = key;
    const summary = document.createElement('summary');
    const name = document.createElement('span');
    name.className = 'inspector-key';
    name.textContent = key;
    const status = document.createElement('span');
    status.className = 'inspector-status';
    summary.append(name, status);
    const pre = document.createElement('pre');
    details.append(summary, pre);

    entry = { details, status, pre, pending: null };
    details.addEventListener('toggle', () => { if (details.open) this.#render(entry); });
    this.#entries.set(key, entry);

    const next = [...this.root.children].find((el) => el.dataset.key > key);
    this.root.insertBefore(details, next ?? null);
    return entry;
  }
}
