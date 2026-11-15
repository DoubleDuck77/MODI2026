// Port render_textured_moon (neworb.py:724-789): ray-cast sfery per piksel w shaderze, ten sam
// wybór poziomu tekstury (pick_texture_level), próbkowanie najbliższe i oświetlenie
// Lommel–Seeliger z AMBIENT = 0.005 i GAMMA = 2.2. Tło (10, 13, 20) jak screen.fill w neworb.
import * as THREE from 'three';

import { R_MOON } from './orbit-camera.js';

const FALLBACK_LIGHT = (() => {
  const v = [0.35, -0.25, 0.90];
  const n = Math.hypot(...v);
  return v.map((x) => x / n);
})();

const fragmentShader = /* glsl */ `
  #include <common>
  uniform float uDpr, uH, uPanelX, uFocal, uD, uR;
  uniform vec2 uCenter;
  uniform vec3 uC, uRight, uUp, uSun;
  uniform sampler2D uTex;
  uniform vec2 uTexSize;
  void main() {
    vec2 p = vec2(gl_FragCoord.x / uDpr - 0.5, uH - gl_FragCoord.y / uDpr - 0.5);
    if (p.x >= uPanelX) discard;
    float qx = (p.x - uCenter.x) / uFocal;
    float qy = -(p.y - uCenter.y) / uFocal;
    float q2 = qx * qx + qy * qy;
    float qa = 1.0 + q2;
    // discriminant = D² − qa(D² − R²), w postaci bez znoszenia się wielkich liczb
    float disc = qa * uR * uR - q2 * uD * uD;
    if (disc < 0.0) discard;
    float t = (uD - sqrt(disc)) / qa;
    vec3 n = ((uD - t) * uC + t * qx * uRight + t * qy * uUp) / uR;
    float lat = asin(clamp(n.z, -1.0, 1.0));
    float lon = atan(n.y, n.x);
    float ui = mod(floor((lon + PI) / (2.0 * PI) * uTexSize.x), uTexSize.x);
    float vi = clamp(floor((PI * 0.5 - lat) / PI * uTexSize.y), 0.0, uTexSize.y - 1.0);
    vec3 tex = texture2D(uTex, vec2((ui + 0.5) / uTexSize.x, (vi + 0.5) / uTexSize.y)).rgb * 255.0;
    float mu0 = dot(n, uSun);
    float mu = (uD * dot(n, uC) - uR) / (t * sqrt(qa));
    float lit = mu0 > 0.0 ? min(1.0, 2.0 * mu0 / max(mu0 + mu, 1e-6)) : 0.0;
    float illumination = pow(0.005 + (1.0 - 0.005) * lit, 1.0 / 2.2);
    gl_FragColor = vec4(floor(clamp(tex * illumination, 0.0, 255.0)) / 255.0, 1.0);
  }
`;

/** Poziomy tekstury jak load_texture: szerokość ≤ 4096, potem połowy aż do ≤ 512. */
async function loadLevels(url) {
  const img = await new Promise((resolve, reject) => {
    const im = new Image();
    im.onload = () => resolve(im);
    im.onerror = () => reject(new Error(`Failed to load ${url}`));
    im.src = url;
  });
  let w = img.width;
  let h = img.height;
  if (w > 4096) { h = Math.max(1, Math.round((h * 4096) / w)); w = 4096; }
  const levels = [];
  let src = img;
  for (;;) {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const ctx = c.getContext('2d');
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(src, 0, 0, w, h);
    levels.push(c);
    if (w <= 512) break;
    src = c;
    w = Math.floor(w / 2);
    h = Math.max(1, Math.floor(h / 2));
  }
  return levels.map((c) => {
    const t = new THREE.CanvasTexture(c);
    t.flipY = false;
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.generateMipmaps = false;
    t.colorSpace = THREE.NoColorSpace;
    return { tex: t, w: c.width, h: c.height };
  });
}

export function createMoonRenderer(root) {
  const renderer = new THREE.WebGLRenderer({ antialias: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x0a0d14);   // (10, 13, 20)
  renderer.domElement.className = 'orbit-gl';
  root.append(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const uniforms = {
    uDpr: { value: 1 }, uH: { value: 1 }, uPanelX: { value: 1 }, uFocal: { value: 1 }, uD: { value: 6000 }, uR: { value: R_MOON },
    uCenter: { value: new THREE.Vector2() },
    uC: { value: new THREE.Vector3() }, uRight: { value: new THREE.Vector3() }, uUp: { value: new THREE.Vector3() },
    uSun: { value: new THREE.Vector3(...FALLBACK_LIGHT) },
    uTex: { value: null }, uTexSize: { value: new THREE.Vector2(1, 1) },
  };
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
    uniforms, vertexShader: 'void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }', fragmentShader,
    depthTest: false, depthWrite: false,
  }));
  quad.frustumCulled = false;
  scene.add(quad);

  let levels = null;
  const ready = loadLevels('/textures/moon_texture8K.jpg').then((l) => { levels = l; return l; });

  return {
    ready,
    get levels() { return levels; },
    setSize(w, h) {
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = `${w}px`;
      renderer.domElement.style.height = `${h}px`;
    },
    /** Rysuje tło i Księżyc; zwraca false, gdy tarcza za mała (< 2 px) albo brak tekstury. */
    render({ camera: cam, center, focal, sunDir, panelX, height }) {
      const radius = cam.apparentRadius(focal);
      const draw = !!levels && cam.dist > R_MOON && radius >= 2;
      quad.visible = draw;
      if (draw) {
        // pick_texture_level: najmniejszy poziom o szerokości ≥ potrzebnej
        const need = (2.0 * Math.PI * R_MOON * focal) / Math.max(cam.dist - R_MOON, 1e-6);
        let lvl = levels[0];
        for (let i = levels.length - 1; i >= 0; i--) { if (levels[i].w >= need) { lvl = levels[i]; break; } }
        uniforms.uTex.value = lvl.tex;
        uniforms.uTexSize.value.set(lvl.w, lvl.h);
        uniforms.uDpr.value = renderer.getPixelRatio();
        uniforms.uH.value = height;
        uniforms.uPanelX.value = panelX;
        uniforms.uFocal.value = focal;
        uniforms.uD.value = cam.dist;
        uniforms.uCenter.value.set(center[0], center[1]);
        uniforms.uC.value.set(...cam.c);
        uniforms.uRight.value.set(...cam.right);
        uniforms.uUp.value.set(...cam.up);
        uniforms.uSun.value.set(...(sunDir ?? FALLBACK_LIGHT));
      }
      renderer.render(scene, camera);
      return draw;
    },
  };
}
