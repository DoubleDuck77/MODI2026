// Jedno miejsce prawdy dla jednostek i osi sceny. Każda warstwa przelicza współrzędne tylko tędy.
//  - 1 jednostka sceny = 1000 km
//  - ekliptyka J2000 (x → punkt Barana, z → biegun ekliptyki) → Three.js (x, z, −y), oś Y sceny = biegun
//  - widok z powierzchni: N = −Z, E = +X, zenit = +Y

export const KM_PER_SCENE_UNIT = 1000;
const DEG = Math.PI / 180;

/** Wektor w km (ekliptyka / układ ciała) → [x, y, z] w jednostkach sceny. */
export function eclipticKmToScene({ x, y, z }) {
  const k = 1 / KM_PER_SCENE_UNIT;
  return [x * k, z * k, -y * k];
}

/** Punkt na sferze → [x, y, z]; zgodne z UV THREE.SphereGeometry (lon 0 → +X, lon 90°E → −Z, N → +Y). */
export function latLonToScene(latDeg, lonDeg, radius = 1) {
  const la = latDeg * DEG;
  const lo = lonDeg * DEG;
  const bx = Math.cos(la) * Math.cos(lo);
  const by = Math.cos(la) * Math.sin(lo);
  const bz = Math.sin(la);
  return [bx * radius, bz * radius, -by * radius];
}

/** Wysokość/azymut na niebie obserwatora → wersor w widoku powierzchni. */
export function altAzToScene(altDeg, azDeg) {
  const h = altDeg * DEG;
  const a = azDeg * DEG;
  return [Math.cos(h) * Math.sin(a), Math.sin(h), -Math.cos(h) * Math.cos(a)];
}
