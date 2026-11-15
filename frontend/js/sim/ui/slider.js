// Suwak DOM wspólny dla trybów /sim.html (przeniesiony dosłownie z surface/surface-mode.js).

/**
 * Suwak DOM o semantyce Slider z geografia.py:2500-2540 (identycznej z newlunar.Slider):
 * wartość = min + ratio^power · (max − min).
 */
export function makeSlider(parent, { label, min, max, value, power = 1, isInt = false, format }) {
  const wrap = document.createElement('label');
  wrap.className = 'sim-slider';
  const text = document.createElement('span');
  const input = document.createElement('input');
  input.type = 'range';
  input.min = '0';
  input.max = '1';
  input.step = 'any';
  wrap.append(text, input);
  parent.append(wrap);
  const s = {
    min, max, power, isInt, value, label, format, el: wrap, input,
    toRatio(v) {
      return s.max > s.min ? Math.max(0, Math.min(1, (v - s.min) / (s.max - s.min))) ** (1 / s.power) : 0;
    },
    set(v, custom) {
      s.value = v;
      input.value = String(s.toRatio(v));
      s.render(custom);
    },
    render(custom) {
      const str = custom ?? (s.isInt ? String(Math.trunc(s.value)) : s.format(s.value));
      text.textContent = `${s.label}: ${str}`;
    },
    onInput: null,
  };
  // Suwak nie zatrzymuje fokusu (w pygame suwaki nie przejmują klawiatury): po puszczeniu
  // myszy skróty (spacja, 1–5, E, S…) działają od razu.
  input.addEventListener('change', () => input.blur());
  input.addEventListener('pointerup', () => input.blur());
  input.addEventListener('input', () => {
    const v = s.min + Number(input.value) ** s.power * (s.max - s.min);
    s.value = s.isInt ? Math.round(v) : v;
    s.render();
    s.onInput?.(s.value);
  });
  s.set(value);
  return s;
}
