// Warstwa modułu `moon_illumination` — oświetlenie, terminator i cienie na Księżycu.
// Dane: this.data['moon_illumination.state'] (z /frame).
import { BaseLayer } from '../../core/base-layer.js';

export default class MoonIlluminationLayer extends BaseLayer {
  static id = 'moon_illumination';
  static view = 'space';

  // TODO(zespół moon_illumination):
  // - sun_dir_body jako uniform shadera terenu Księżyca (cienie gór i kraterów liczone per piksel w GPU)
  // - linia terminatora z punktów terminator (latLonToScene)
  // - wyróżnienie obiektów z shadows[].in_shadow (np. Shackleton w wiecznym cieniu)
  // - opcjonalnie: znacznik punktu podsłonecznego i podziemskiego (libracja)
}
