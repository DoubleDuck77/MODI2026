// Warstwa modułu `horizon` — widok z powierzchni Księżyca: horyzont, Ziemia i Słońce na niebie.
// Dane: this.data['horizon.view'] (z /frame, zależy od obserwatora: this.ctx.observer).
import { BaseLayer } from '../../core/base-layer.js';

export default class HorizonLayer extends BaseLayer {
  static id = 'horizon';
  static view = 'surface';

  // TODO(zespół horizon):
  // - sylwetka horyzontu z profile.elevation_deg (krok profile.az_step_deg czytać z payloadu)
  // - Ziemia i Słońce jako billboardy w kierunku altAzToScene(alt_deg, az_deg) z ../../core/units.js
  // - róża kierunków N/E/S/W (N = −Z, E = +X)
  // - opcjonalnie: niebo gwiazdowe obrócone bazą local_basis
}
