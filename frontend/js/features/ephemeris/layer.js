// Warstwa modułu `ephemeris` — korelacja położeń Ziemi, Księżyca i Słońca.
// Dane: this.data['ephemeris.state'] (z /frame); szereg: this.ctx.api.getJson(<path endpointu series>, {start, end, step_hours}).
import { BaseLayer } from '../../core/base-layer.js';

export default class EphemerisLayer extends BaseLayer {
  static id = 'ephemeris';
  static view = 'space';

  // TODO(zespół ephemeris):
  // - Ziemia w (0, 0, 0), Księżyc w eclipticKmToScene(moon_km) z ../../core/units.js
  // - ustawić kierunek this.ctx.scene.sunLight z sun_km (z tego światła korzystają inne warstwy)
  // - płynna animacja: pobrać `series` dla okna wokół clock.t i interpolować w update(), zamiast pytać co klatkę
  // - HUD: odległość Ziemia–Księżyc, faza Księżyca (moon_phase), faza Ziemi widzianej z Księżyca
}
