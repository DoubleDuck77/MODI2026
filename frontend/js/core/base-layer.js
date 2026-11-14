// Klasa bazowa warstwy frontendu. Jeden moduł backendu = jedna warstwa:
//   frontend/js/features/<feature_id>/layer.js → export default class extends BaseLayer
// static id i static view muszą być równe id i view z manifestu.

import * as THREE from 'three';

export class BaseLayer {
  static id = '';
  static view = 'space';

  /** ctx = { api, scene, clock, observer, inspector, feature } (feature = wpis z manifestu). */
  constructor(ctx) {
    this.ctx = ctx;
    this.feature = ctx.feature;
    this.group = new THREE.Group();
    this.group.name = `layer:${this.constructor.id}`;
    this.data = {};
  }

  /** Jednorazowa inicjalizacja (np. wczytanie tekstur). */
  async init() {}

  /** Nowe dane z endpointu (static raz na start, frame przy każdej zmianie czasu/obserwatora). */
  onData(key, payload) {
    this.data[key] = payload;
    this.ctx.inspector.show(key, payload);
  }

  /** Wywoływane co klatkę dla widocznych warstw; tutaj tylko interpolacja i animacja, bez sieci. */
  update(tMs, dtSeconds) {}

  setVisible(visible) { this.group.visible = Boolean(visible); }

  get visible() { return this.group.visible; }

  /** Klucze endpointów tej warstwy pobierane przez /api/v1/frame. */
  frameKeys() {
    return this.feature.endpoints.filter((e) => e.frame).map((e) => e.key);
  }

  dispose() {
    this.group.removeFromParent();
    this.group.traverse((obj) => {
      obj.geometry?.dispose();
      const materials = Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : [];
      for (const m of materials) {
        for (const value of Object.values(m)) if (value?.isTexture) value.dispose();
        m.dispose();
      }
    });
  }
}
