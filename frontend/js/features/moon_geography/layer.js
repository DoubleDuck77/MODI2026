// Warstwa modułu `moon_geography` — kratery, góry, morza i teren Księżyca.
// Dane static (raz na start): this.data['moon_geography.features'], this.data['moon_geography.terrain'].
import { BaseLayer } from '../../core/base-layer.js';

export default class MoonGeographyLayer extends BaseLayer {
  static id = 'moon_geography';
  static view = 'space';

  // TODO(zespół moon_geography):
  // - sfera Księżyca o promieniu radius_km / KM_PER_SCENE_UNIT; najpierw color_map_preview, potem color_map (progresywnie)
  // - displacement z height_map (gdy nie-null) według height_range_m
  // - etykiety kraterów/gór/mórz w latLonToScene(center.lat_deg, center.lon_deg, R) z ../../core/units.js
  // - pozycję sfery brać z warstwy ephemeris (moon_km), nie liczyć jej tutaj
}
