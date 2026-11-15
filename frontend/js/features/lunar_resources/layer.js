// Warstwa modułu `lunar_resources` — zasoby geochemiczne z radius.py.
// Pełna wizualizacja żyje na osobnej stronie /sim.html#resources (js/sim/resources/*); tu tylko zaślepka,
// żeby manifest strony głównej mógł załadować moduł bez błędu.
import { BaseLayer } from '../../core/base-layer.js';

export default class LunarResourcesLayer extends BaseLayer {
  static id = 'lunar_resources';
  static view = 'surface';
}
