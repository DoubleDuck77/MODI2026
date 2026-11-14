// Tymczasowa zaślepka trybu — zastępowana w kolejnych taskach planu.
export function createOrbitMode({ root }) {
  root.innerHTML = '<p style="padding:16px">Tryb w budowie…</p>';
  return { activate() {}, deactivate() {} };
}
