// Warstwa modułu `line_of_sight` — czy obserwator na Księżycu widzi Ziemię.
// Dane: this.data['line_of_sight.point'] (z /frame); okna: this.ctx.api.getJson(<path endpointu windows>, {...}).
import { BaseLayer } from '../../core/base-layer.js';

export default class LineOfSightLayer extends BaseLayer {
  static id = 'line_of_sight';
  static view = 'surface';

  // TODO(zespół line_of_sight):
  // - promień od obserwatora do Ziemi (altAzToScene(earth.alt_deg, earth.az_deg)), zielony gdy earth_visible, czerwony gdy nie
  // - HUD: clearance_deg, visible_disk_fraction, blocked_by (nazwa z moon_geography)
  // - oś czasu z `windows` dla bieżącego obserwatora (pobierać przy zmianie obserwatora, nie co klatkę)
}
