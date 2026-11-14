// Warstwa modułu `lagrange` — punkty L1–L5 układu Ziemia–Księżyc.
// Dane: this.data['lagrange.points'] (z /frame).
import { BaseLayer } from '../../core/base-layer.js';

export default class LagrangeLayer extends BaseLayer {
  static id = 'lagrange';
  static view = 'space';

  // TODO(zespół lagrange):
  // - znaczniki L1–L5 w eclipticKmToScene(position_km) z etykietami
  // - inny styl dla punktów stable (L4, L5) i niestabilnych (L1–L3)
  // - opcjonalnie: przełącznik widoku w układzie rotującym (rotating_frame + position_rotating)
  // - opcjonalnie: linie Ziemia–L1–Księżyc–L2 i trójkąty L4/L5
}
