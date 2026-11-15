// Wspólna scena Three.js: jeden renderer, jedna pętla animacji, dwie grupy widoków.
// Warstwy dodają obiekty wyłącznie do własnej grupy (BaseLayer.group), a ta trafia do views[feature.view].

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const VIEW_PRESETS = {
  space: { position: [0, 250, 550], target: [0, 0, 0] },
  surface: { position: [0, 0, 0.01], target: [0, 0, -1] },
};

export class SceneContext {
  #callbacks = [];
  #clock = new THREE.Clock(false);

  constructor(container) {
    this.container = container;

    this.renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x05070c);
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.001, 5000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.04));
    // Kierunek Słońca ustawia warstwa `ephemeris` (sun_km); pozostałe warstwy tylko z niego korzystają.
    this.sunLight = new THREE.DirectionalLight(0xffffff, 2.5);
    this.sunLight.position.set(1, 0, 0);
    this.scene.add(this.sunLight);

    this.views = { space: new THREE.Group(), surface: new THREE.Group() };
    for (const [name, group] of Object.entries(this.views)) {
      group.name = `view:${name}`;
      this.scene.add(group);
    }
    // Osie konwencji: X (czerwona) = punkt Barana, Y (zielona) = biegun ekliptyki, Z (niebieska) = −Y ekliptyki.
    this.views.space.add(new THREE.AxesHelper(50));

    new ResizeObserver(() => this.#resize()).observe(container);
    this.#resize();
    this.setView('space');
  }

  get activeView() { return this._activeView; }

  setView(name) {
    if (!(name in this.views)) throw new Error(`Unknown view: ${name}`);
    this._activeView = name;
    for (const [n, group] of Object.entries(this.views)) group.visible = n === name;
    const preset = VIEW_PRESETS[name];
    this.camera.position.set(...preset.position);
    this.controls.target.set(...preset.target);
    this.controls.update();
  }

  /** Rejestruje callback wywoływany raz na klatkę z dt w sekundach; zwraca funkcję wyrejestrowującą. */
  onFrame(cb) {
    this.#callbacks.push(cb);
    return () => { this.#callbacks = this.#callbacks.filter((c) => c !== cb); };
  }

  start() {
    this.#clock.start();
    this.renderer.setAnimationLoop(() => {
      const dt = Math.min(this.#clock.getDelta(), 0.1); // po powrocie do karty nie skaczemy o minuty
      for (const cb of this.#callbacks) cb(dt);
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    });
  }

  #resize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }
}
