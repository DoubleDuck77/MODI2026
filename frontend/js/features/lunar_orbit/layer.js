// Warstwa modułu `lunar_orbit` — symulator orbit z neworb.py.
// Pełna wizualizacja żyje na osobnej stronie /sim.html#orbit (js/sim/orbit/*); tu tylko zaślepka,
// żeby manifest strony głównej mógł załadować moduł bez błędu.
import { BaseLayer } from '../../core/base-layer.js';

export default class LunarOrbitLayer extends BaseLayer {
  static id = 'lunar_orbit';
  static view = 'space';
}
