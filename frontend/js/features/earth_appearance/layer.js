// Warstwa modułu `earth_appearance` — Ziemia: rotacja, chmury i światła miast po stronie nocnej.
// Dane: this.data['earth_appearance.state'] (z /frame).
import { BaseLayer } from '../../core/base-layer.js';

export default class EarthAppearanceLayer extends BaseLayer {
  static id = 'earth_appearance';
  static view = 'space';

  // TODO(zespół earth_appearance):
  // - kula Ziemi z shaderem dzień/noc: day_texture / night_texture mieszane wg elewacji Słońca z subsolar_point;
  //   światła pełne przy elewacji <= city_lights.on_below_sun_elevation_deg, zero przy >= on_below + fade_deg
  // - osobna sfera chmur (R + clouds.altitude_km) obracana clouds.angle_deg NIEZALEŻNIE od rotation.angle_deg;
  //   w update() ekstrapolować kąty z rate_deg_per_hour, żeby obrót był płynny między odpowiedziami /frame
  // - znaczniki miast przełączane city_lights.cities[].lights_on
  // - nachylenie osi axial_tilt_deg
}
