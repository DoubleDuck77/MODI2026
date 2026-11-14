// Niebo trybu „Powierzchnia” — port newlunar.main() (gwiazdy, siatka wysokości, róża kierunków) oraz
// draw_telescopic_sun (newlunar.py:1179-1230) i draw_telescopic_earth (newlunar.py:1233-1454).
// Słońce i Ziemia to billboardy o rozmiarze w pikselach ekranu z shaderem per piksel — ten sam
// algorytm co siatka pikseli w pygame. Teren (bliżej) zasłania wszystko testem głębokości, tak jak
// w pygame teren rysowany jest po niebie.
import * as THREE from 'three';

import { enuToScene } from './terrain-mesh.js';

const DEG = Math.PI / 180;
const R_EARTH = 6371.0;
const R_MOON = 1737.4;
const R_SUN = 696340.0;
const D_STARS = 8000;
const D_GRID = 6000;
const D_SUN = 5000;
const D_EARTH = 4000;

const billboardVertex = /* glsl */ `
  #include <common>
  #include <logdepthbuf_pars_vertex>
  varying vec2 vUv;
  void main() {
    vUv = uv;
    vec4 mvPosition = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
    vec2 scale = vec2(length(modelMatrix[0].xyz), length(modelMatrix[1].xyz));
    mvPosition.xy += position.xy * scale;
    gl_Position = projectionMatrix * mvPosition;
    #include <logdepthbuf_vertex>
  }
`;

// draw_telescopic_sun: współrzędne w promieniach tarczy, pociemnienie brzegowe, granulacja, korona.
const sunFragment = /* glsl */ `
  #include <common>
  #include <logdepthbuf_pars_fragment>
  uniform float uOuter;      // halo_r / r_sun
  uniform float uHaloMult;
  uniform float uGranulation;
  varying vec2 vUv;
  void main() {
    #include <logdepthbuf_fragment>
    vec2 g = (vUv * 2.0 - 1.0) * uOuter;
    float gx = g.x, gy = -g.y;
    float dist = sqrt(gx * gx + gy * gy);
    vec4 c;
    if (dist <= 1.0) {
      float mu = sqrt(clamp(1.0 - dist * dist, 0.0, 1.0));
      float ld = 0.45 + 0.55 * pow(mu, 0.50);
      if (uGranulation > 0.5) ld = clamp(ld + 0.028 * sin(gx * 55.0) * cos(gy * 55.0), 0.25, 1.05);
      c = vec4(floor(clamp(255.0 * min(1.0, ld * 1.06), 0.0, 255.0)),
               floor(clamp(246.0 * ld, 0.0, 255.0)),
               floor(clamp(218.0 * pow(ld, 1.15), 0.0, 255.0)), 255.0) / 255.0;
    } else if (dist <= uHaloMult) {
      float tc = (dist - 1.0) / (uHaloMult - 1.0);
      float glow = exp(-2.6 * tc) * (1.0 - tc);
      c = vec4(255.0, 228.0, 165.0, floor(clamp(220.0 * glow, 0.0, 255.0))) / 255.0;
    } else {
      discard;
    }
    gl_FragColor = c;
  }
`;

// draw_telescopic_earth: wszystkie wektory w ENU obserwatora [N, E, U], jak w pygame.
const earthFragment = /* glsl */ `
  #include <common>
  #include <logdepthbuf_pars_fragment>
  uniform float uOuter;            // r_outer / r_earth
  uniform vec3 uEx, uEy, uEz;      // e_x_cam, e_y_cam, e_z_cam
  uniform vec3 uSun;               // sun_from_earth_enu
  uniform vec3 uMoon;              // moon_from_earth_enu [km]
  uniform float uSunDist;          // sun_dist_from_earth [km]
  uniform float uMoonShadow;       // 1 gdy dot(moon, sun) > 0
  uniform vec3 uX, uY, uZ;         // ecef_axes_enu
  uniform float uCloudOffset;
  uniform float uRing;             // eclipse_ring_factor
  uniform float uDarkExposure;     // dark_side_exposure
  uniform sampler2D uDay;          // flipY: v obrazu = 1 − uv.y
  uniform sampler2D uNight;        // DataTexture poziomu mip (bez flipY)
  uniform sampler2D uClouds;
  varying vec2 vUv;
  void main() {
    #include <logdepthbuf_fragment>
    vec2 g = (vUv * 2.0 - 1.0) * uOuter;
    float gx = g.x, gy = -g.y;
    float d2 = gx * gx + gy * gy;
    if (d2 > 1.28) discard;
    if (d2 <= 1.0) {
      float gz = sqrt(1.0 - d2);
      vec3 n = gx * uEx - gy * uEy + gz * uEz;
      float lat = asin(clamp(dot(n, uZ), -1.0, 1.0));
      float lon = atan(dot(n, uY), dot(n, uX));
      float u = (lon + PI) / (2.0 * PI);
      float v = (PI * 0.5 - lat) / PI;

      vec3 day = texture2D(uDay, vec2(u, 1.0 - v)).rgb * 255.0;
      vec3 rawNight = texture2D(uNight, vec2(u, v)).rgb;
      vec3 cleanNight = clamp((rawNight - 0.055) / 0.945, 0.0, 1.0);
      vec3 night = pow(cleanNight, vec3(0.88)) * 255.0 * (1.15 * uDarkExposure);

      float cosSun = dot(n, uSun);
      float tw = clamp((cosSun + 0.07) / 0.15, 0.0, 1.0);
      float dayBlend = tw * tw * (3.0 - 2.0 * tw);
      float sd = pow(clamp(cosSun, 0.0, 1.0), 0.78);

      if (uMoonShadow > 0.5) {
        vec3 rel = ${R_EARTH.toFixed(1)} * n - uMoon;
        float along = dot(rel, uSun);
        if (along < 0.0) {
          float behind = -along;
          float perp = length(rel + behind * uSun);
          float rPen = ${R_MOON.toFixed(1)} + behind * (${(R_SUN + R_MOON).toFixed(1)}) / max(1.0, uSunDist);
          float rUmb = max(0.0, ${R_MOON.toFixed(1)} - behind * (${(R_SUN - R_MOON).toFixed(1)}) / max(1.0, uSunDist));
          if (perp < rPen) {
            float pt = clamp((perp - rUmb) / max(rPen - rUmb, 1.0), 0.0, 1.0);
            sd *= 0.08 + 0.92 * (pt * pt * (3.0 - 2.0 * pt));
          }
        }
      }

      float tg = exp(-pow((cosSun - 0.01) / 0.095, 2.0)) * (cosSun > -0.08 ? 1.0 : 0.0);
      vec3 litDay = day * (0.02 + 0.98 * sd);
      litDay.r += 36.0 * tg;
      litDay.g += 12.0 * tg;

      float cRaw = texture2D(uClouds, vec2(fract(u - uCloudOffset), 1.0 - v)).r;
      float ca = pow(clamp((cRaw - 0.04) / 0.96, 0.0, 1.0), 0.90) * 0.92;
      vec3 cloudLit = vec3(252.0 * (0.03 + 0.97 * sd) + 46.0 * tg,
                           253.0 * (0.03 + 0.97 * sd) + 16.0 * tg,
                           255.0 * (0.04 + 0.96 * sd));
      litDay = litDay * (1.0 - ca) + cloudLit * ca;
      night = night * (1.0 - 0.55 * ca);

      float twCities = pow(clamp((0.04 - cosSun) / 0.14, 0.0, 1.0), 1.4);
      vec3 outRgb = litDay * dayBlend + night * twCities;

      float limbGeom = pow(1.0 - gz, 2.6);
      float dayLimb = limbGeom * clamp(cosSun + 0.22, 0.0, 1.0) * (1.0 - 0.75 * uRing);
      float eclLimb = limbGeom * uRing;
      outRgb += vec3(75.0, 155.0, 250.0) * dayLimb + vec3(245.0, 95.0, 35.0) * eclLimb;
      gl_FragColor = vec4(floor(clamp(outRgb, 0.0, 255.0)) / 255.0, 1.0);
    } else {
      float dh = sqrt(d2);
      float hf = pow(clamp(1.0 - (dh - 1.0) / 0.13, 0.0, 1.0), 2.0);
      vec3 nHalo = gx * uEx - gy * uEy;
      float sunFacing = clamp(dot(nHalo, uSun) + 0.30, 0.04, 1.0);
      float strength = max(sunFacing, 0.85 * uRing);
      vec3 hc = floor(vec3(75.0, 155.0, 250.0) * (1.0 - uRing) + vec3(235.0, 88.0, 32.0) * uRing);
      gl_FragColor = vec4(hc / 255.0, floor(clamp(150.0 * hf * strength, 0.0, 255.0)) / 255.0);
    }
  }
`;

const starVertex = /* glsl */ `
  #include <common>
  #include <logdepthbuf_pars_vertex>
  attribute float brightness;
  uniform float uPointSize;
  varying float vB;
  varying float vVisible;
  void main() {
    vB = brightness;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vVisible = world.y / ${D_STARS.toFixed(1)} > sin(-0.1) ? 1.0 : 0.0;   // s_alt > −0.1
    gl_Position = projectionMatrix * viewMatrix * world;
    gl_PointSize = uPointSize;
    #include <logdepthbuf_vertex>
  }
`;
const starFragment = /* glsl */ `
  #include <logdepthbuf_pars_fragment>
  varying float vB;
  varying float vVisible;
  void main() {
    #include <logdepthbuf_fragment>
    if (vVisible < 0.5) discard;
    gl_FragColor = vec4(vec3(vB / 255.0), 1.0);
  }
`;

/** Piramida mip „0.45·średnia + 0.55·max” jak build_night_mipmaps (newlunar.py:209-224). */
function buildNightMips(img) {
  const c = document.createElement('canvas');
  c.width = img.width;
  c.height = img.height;
  const ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  let cur = { w: img.width, h: img.height, data: ctx.getImageData(0, 0, img.width, img.height).data };
  const mips = [cur];
  while (cur.h >= 256 && cur.w >= 512) {
    const h = Math.floor(cur.h / 2) * 2;
    const w = Math.floor(cur.w / 2) * 2;
    const nh = h / 2;
    const nw = w / 2;
    const out = new Uint8ClampedArray(nw * nh * 4);
    for (let y = 0; y < nh; y++) {
      for (let x = 0; x < nw; x++) {
        for (let k = 0; k < 3; k++) {
          const a = cur.data[((2 * y) * cur.w + 2 * x) * 4 + k];
          const b = cur.data[((2 * y) * cur.w + 2 * x + 1) * 4 + k];
          const cc = cur.data[((2 * y + 1) * cur.w + 2 * x) * 4 + k];
          const d = cur.data[((2 * y + 1) * cur.w + 2 * x + 1) * 4 + k];
          const v = 0.45 * ((a + b + cc + d) / 4) + 0.55 * Math.max(a, b, cc, d);
          out[(y * nw + x) * 4 + k] = Math.trunc(Math.min(255, Math.max(0, v)));   // astype(np.uint8)
        }
        out[(y * nw + x) * 4 + 3] = 255;
      }
    }
    cur = { w: nw, h: nh, data: out };
    mips.push(cur);
  }
  return mips.map((m) => {
    const t = new THREE.DataTexture(new Uint8Array(m.data.buffer.slice(0)), m.w, m.h, THREE.RGBAFormat);
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.wrapS = THREE.RepeatWrapping;
    t.needsUpdate = true;
    return t;
  });
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Nie udało się wczytać ${url}`));
    img.src = url;
  });
}

function makeLabel(parent, text, css) {
  const el = document.createElement('div');
  el.className = 'sim-label';
  el.textContent = text;
  Object.assign(el.style, css);
  el.hidden = true;
  parent.append(el);
  return el;
}

export function createSky(scene, renderer) {
  const placeholder = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1, THREE.RGBAFormat);
  placeholder.needsUpdate = true;

  // --- gwiazdy ---
  const starMat = new THREE.ShaderMaterial({
    uniforms: { uPointSize: { value: 1 } },
    vertexShader: starVertex,
    fragmentShader: starFragment,
  });
  let stars = null;

  // --- siatka wysokości 0°, 30°, 60° (newlunar.py:2015-2022), kolor (25, 35, 50) ---
  const gridMat = new THREE.LineBasicMaterial({ color: 0x192332 });
  for (const aDeg of [0, 30, 60]) {
    const pts = [];
    for (let z = 0; z < 365; z += 5) {
      const a = aDeg * DEG;
      const az = z * DEG;
      pts.push(enuToScene([Math.cos(a) * Math.cos(az), Math.cos(a) * Math.sin(az), Math.sin(a)]).multiplyScalar(D_GRID));
    }
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat);
    line.frustumCulled = false;
    line.renderOrder = -3;
    scene.add(line);
  }

  // --- Słońce ---
  const sunMat = new THREE.ShaderMaterial({
    uniforms: { uOuter: { value: 3.8 }, uHaloMult: { value: 3.8 }, uGranulation: { value: 0 } },
    vertexShader: billboardVertex,
    fragmentShader: sunFragment,
    transparent: true,
    depthWrite: false,
  });
  const sun = new THREE.Sprite(sunMat);
  sun.renderOrder = 1;
  sun.frustumCulled = false;
  scene.add(sun);

  // --- Ziemia ---
  const earthUniforms = {
    uOuter: { value: 1.14 },
    uEx: { value: new THREE.Vector3() }, uEy: { value: new THREE.Vector3() }, uEz: { value: new THREE.Vector3() },
    uSun: { value: new THREE.Vector3() }, uMoon: { value: new THREE.Vector3() },
    uSunDist: { value: 1.5e8 }, uMoonShadow: { value: 0 },
    uX: { value: new THREE.Vector3(1, 0, 0) }, uY: { value: new THREE.Vector3(0, 1, 0) }, uZ: { value: new THREE.Vector3(0, 0, 1) },
    uCloudOffset: { value: 0 }, uRing: { value: 0 }, uDarkExposure: { value: 1 },
    uDay: { value: placeholder }, uNight: { value: placeholder }, uClouds: { value: placeholder },
  };
  const earthMat = new THREE.ShaderMaterial({
    uniforms: earthUniforms,
    vertexShader: billboardVertex,
    fragmentShader: earthFragment,
    transparent: true,
    depthWrite: false,
  });
  const earth = new THREE.Sprite(earthMat);
  earth.renderOrder = 2;
  earth.frustumCulled = false;
  scene.add(earth);

  // Tekstury Ziemi — te, które faktycznie ładuje newlunar.load_earth_textures (newlunar.py:227-285):
  // earth_day8K.jpg; noc: earth_night.jpg (nazwa earrth_night8K.jpg nie pasuje do wzorców newlunar);
  // chmury earth_clouds8K.jpg (kanał 0).
  let nightMips = [];
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  const texLoader = new THREE.TextureLoader();
  for (const [key, url] of [['uDay', '/textures/earth_day8K.jpg'], ['uClouds', '/textures/earth_clouds8K.jpg']]) {
    texLoader.load(url, (t) => {
      t.wrapS = THREE.RepeatWrapping;
      t.anisotropy = maxAniso;
      earthUniforms[key].value = t;
    });
  }
  loadImage('/textures/earth_night.jpg').then((img) => { nightMips = buildNightMips(img); }).catch(console.error);

  // --- etykiety ---
  let labelLayer = null;
  const labelEls = {};
  const COMPASS = [['N', 0], ['NE', 45], ['E', 90], ['SE', 135], ['S', 180], ['SW', 225], ['W', 270], ['NW', 315]];
  function ensureLabels(layer) {
    if (labelLayer === layer) return;
    labelLayer = layer;
    for (const [name] of COMPASS) {
      labelEls[name] = makeLabel(layer, name, { font: 'bold 18px Consolas, ui-monospace, monospace', color: name === 'N' ? 'rgb(255,90,90)' : 'rgb(210,220,235)' });
    }
    labelEls.sun = makeLabel(layer, 'Słońce', { font: '15px Consolas, ui-monospace, monospace', color: 'rgb(255,230,150)', transform: 'none' });
    labelEls.earth = makeLabel(layer, 'Ziemia', { font: '15px Consolas, ui-monospace, monospace', color: 'rgb(130,200,255)', transform: 'none' });
  }

  const tmp = new THREE.Vector3();
  function project(dirEnu, camera, size, fwdEnu) {
    const zCam = dirEnu[0] * fwdEnu[0] + dirEnu[1] * fwdEnu[1] + dirEnu[2] * fwdEnu[2];
    if (zCam <= 0.05) return null;
    enuToScene(dirEnu, tmp).multiplyScalar(1000).project(camera);
    return { x: (tmp.x + 1) / 2 * size.cw, y: (1 - tmp.y) / 2 * size.ch, zCam };
  }
  /** Kierunek ENU piksela ekranu (do testu zasłonięcia etykiety przez teren). */
  function unprojectAltAz(x, y, camera, size) {
    tmp.set((x / size.cw) * 2 - 1, 1 - (y / size.ch) * 2, 0.5).unproject(camera).normalize();
    const n = -tmp.z;
    const e = tmp.x;
    const u = tmp.y;
    return { alt: Math.asin(Math.max(-1, Math.min(1, u))), az: Math.atan2(e, n) };
  }
  function placeLabel(el, x, y, size) {
    const inside = x >= 0 && x < size.cw && y >= 0 && y < size.ch;
    el.hidden = !inside;
    if (inside) { el.style.left = `${x}px`; el.style.top = `${y}px`; }
  }

  const v3 = (a) => new THREE.Vector3(a[0], a[1], a[2]);

  return {
    setStars(field) {
      if (stars) { scene.remove(stars); stars.geometry.dispose(); }
      const pos = new Float32Array(field.ecliptic_xyz.length * 3);
      field.ecliptic_xyz.forEach((v, i) => pos.set([v[0] * D_STARS, v[1] * D_STARS, v[2] * D_STARS], i * 3));
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      g.setAttribute('brightness', new THREE.BufferAttribute(new Float32Array(field.brightness), 1));
      stars = new THREE.Points(g, starMat);
      stars.frustumCulled = false;
      stars.matrixAutoUpdate = false;
      stars.renderOrder = -4;
      scene.add(stars);
    },
    setHorizon() {},
    /**
     * view — stan nieba (LunarSky po interpolacji); ctx: { camera, fov, size, camAlt, camAz,
     * clockMs, yearStartMs, animTime, horizonAt, labels }.
     */
    update(view, ctx) {
      const { camera, fov, size, camAlt, camAz } = ctx;
      ensureLabels(ctx.labels);
      const focal = (size.ch / 2) / Math.tan(fov / 2);
      const fwd = [Math.cos(camAlt) * Math.cos(camAz), Math.cos(camAlt) * Math.sin(camAz), Math.sin(camAlt)];
      const right = [-Math.sin(camAz), Math.cos(camAz), 0];
      const camUp = [-Math.sin(camAlt) * Math.cos(camAz), -Math.sin(camAlt) * Math.sin(camAz), Math.cos(camAlt)];

      // gwiazdy: ekliptyka → ENU (ecliptic_to_enu) → scena
      starMat.uniforms.uPointSize.value = renderer.getPixelRatio();
      if (stars) {
        const M = view.ecliptic_to_enu;   // wiersze N, E, U
        const m = new THREE.Matrix4().set(
          M[1][0], M[1][1], M[1][2], 0,      // x = E
          M[2][0], M[2][1], M[2][2], 0,      // y = U
          -M[0][0], -M[0][1], -M[0][2], 0,   // z = −N
          0, 0, 0, 1,
        );
        stars.matrix.copy(m);
        stars.matrixWorldNeedsUpdate = true;
      }

      // Słońce
      let sunLabelAt = null;
      const sunDir = view.sun.dir_enu;
      const sp = project(sunDir, camera, size, fwd);
      sun.visible = !!sp;
      if (sp) {
        const angSun = view.sun.angular_radius_deg * DEG;
        const rExact = Math.tan(angSun) * focal / sp.zCam;
        const rSun = Math.max(4.0, rExact);
        const haloMult = rSun < 20.0 ? 3.8 : 2.5;
        const haloR = Math.trunc(Math.min(Math.max(rSun * haloMult, 22), Math.max(size.cw, size.ch)));
        sun.position.copy(enuToScene(sunDir)).multiplyScalar(D_SUN);
        const half = haloR * D_SUN * sp.zCam / focal;
        sun.scale.set(2 * half, 2 * half, 1);
        sunMat.uniforms.uOuter.value = haloR / rSun;
        sunMat.uniforms.uHaloMult.value = haloMult;
        sunMat.uniforms.uGranulation.value = rSun > 18.0 ? 1 : 0;
        const rLabel = Math.max(6, Math.trunc(rExact));
        sunLabelAt = [sp.x + rLabel + 6, sp.y - 8];
      }

      // Ziemia
      let earthDisk = null;
      const earthDir = view.earth.dir_enu;
      const ep = project(earthDir, camera, size, fwd);
      earth.visible = !!ep;
      if (ep) {
        const angEarth = view.earth.angular_radius_deg * DEG;
        const rExact = Math.tan(angEarth) * focal / ep.zCam;
        const rEarth = Math.max(6.5, rExact);
        const pad = Math.trunc(Math.max(4, rEarth * 0.14));
        const rOuter = rEarth + pad;
        earth.position.copy(enuToScene(earthDir)).multiplyScalar(D_EARTH);
        const half = rOuter * D_EARTH * ep.zCam / focal;
        earth.scale.set(2 * half, 2 * half, 1);

        // baza kamery dla tarczy (newlunar.py:1265-1283)
        const ez = v3(earthDir).multiplyScalar(-1);
        const ex = v3(right).addScaledVector(ez, -v3(right).dot(ez));
        if (ex.length() < 1e-6) ex.copy(v3(camUp).cross(ez).multiplyScalar(-1));
        ex.normalize();
        const ey = v3(camUp).addScaledVector(ez, -v3(camUp).dot(ez));
        ey.addScaledVector(ex, -ey.dot(ex));
        if (ey.length() < 1e-6) ey.copy(ez.clone().cross(ex).multiplyScalar(-1));
        ey.normalize();
        const u = earthUniforms;
        u.uOuter.value = rOuter / rEarth;
        u.uEx.value.copy(ex); u.uEy.value.copy(ey); u.uEz.value.copy(ez);
        u.uSun.value.copy(v3(view.sun_from_earth_enu));
        u.uMoon.value.copy(v3(view.moon_from_earth_enu_km));
        u.uSunDist.value = view.sun_distance_from_earth_km;
        u.uMoonShadow.value = u.uMoon.value.dot(u.uSun.value) > 0 ? 1 : 0;
        const [X, Y, Z] = view.earth_axes_enu;
        u.uX.value.copy(v3(X)); u.uY.value.copy(v3(Y)); u.uZ.value.copy(v3(Z));
        // cloud_offset = (d_rel·0.015 + anim_time·0.0012) % 1, d_rel = dni od początku roku (newlunar.py:2038-2040)
        const dRel = (ctx.clockMs - ctx.yearStartMs) / 86_400_000;
        u.uCloudOffset.value = ((dRel * 0.015 + ctx.animTime * 0.0012) % 1 + 1) % 1;
        u.uRing.value = view.eclipse_ring_factor;
        u.uDarkExposure.value = view.dark_side_exposure;
        if (nightMips.length) {
          const baseW = nightMips[0].image.width;
          const tpp = baseW / Math.max(1.0, 2 * Math.PI * rEarth);
          const idx = Math.min(nightMips.length - 1, Math.max(0, Math.round(Math.log2(Math.max(1.0, tpp)))));
          u.uNight.value = nightMips[idx];
        }
        const rLabel = Math.max(8, Math.trunc(rExact));
        placeLabelOccluded(labelEls.earth, ep.x + rLabel + 8, ep.y - 8, ctx);
        earthDisk = [ep.x, ep.y, rEarth];
      } else {
        labelEls.earth.hidden = true;
      }
      // Etykieta Słońca: w pygame rysowana przed Ziemią i terenem — zasłaniają ją oba.
      if (sunLabelAt) {
        placeLabelOccluded(labelEls.sun, sunLabelAt[0], sunLabelAt[1], ctx);
        if (earthDisk && Math.hypot(sunLabelAt[0] + 4 - earthDisk[0], sunLabelAt[1] + 8 - earthDisk[1]) < earthDisk[2]) {
          labelEls.sun.hidden = true;
        }
      } else {
        labelEls.sun.hidden = true;
      }

      // róża kierunków nad lokalnym horyzontem (newlunar.py:2067-2074) — rysowana po terenie
      for (const [name, deg] of COMPASS) {
        const az = deg * DEG;
        const hAlt = ctx.horizonAt(az) + Math.max(1.2 * DEG, fov * 0.02);
        const p = project([Math.cos(hAlt) * Math.cos(az), Math.cos(hAlt) * Math.sin(az), Math.sin(hAlt)], camera, size, fwd);
        if (p) placeLabel(labelEls[name], p.x, p.y, size); else labelEls[name].hidden = true;
      }
    },
  };

  // Etykiety Słońca/Ziemi są w pygame rysowane przed terenem, więc teren je zasłania:
  // pokazujemy je tylko, gdy piksel etykiety leży nad horyzontem terenu.
  function placeLabelOccluded(el, x, y, ctx) {
    const { camera, size } = ctx;
    const inside = x >= 0 && x < size.cw && y >= 0 && y < size.ch;
    if (!inside) { el.hidden = true; return; }
    const { alt, az } = unprojectAltAz(x + 4, y + 8, camera, size);
    el.hidden = alt < ctx.horizonAt(az);
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
  }
}
