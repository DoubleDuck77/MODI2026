// Warstwa modułu `lunar_surface` — widok z powierzchni Księżyca z newlunar.py.
// Pełna wizualizacja żyje na osobnej stronie /sim.html#surface (js/sim/surface/*); tu tylko zaślepka,
// żeby manifest strony głównej mógł załadować moduł bez błędu.
import { BaseLayer } from '../../core/base-layer.js';

export default class LunarSurfaceLayer extends BaseLayer {
  static id = 'lunar_surface';
  static view = 'surface';
}
