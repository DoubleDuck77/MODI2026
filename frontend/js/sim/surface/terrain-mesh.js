// Mesh terenu z siatki biegunowej lunar_surface.terrain (720 az × 480 promieni + wierzchołek środkowy).
// Cieniowanie 1:1 z newlunar.LunarTerrain3D.draw_3d (newlunar.py:1097-1111) i normalne ze wzmocnieniem
// reliefu RELIEF_GAIN = 1.65 (newlunar.py:667-675). Scena: km względem oka obserwatora, E = +X, U = +Y, N = −Z.
import * as THREE from 'three';

export const R_MOON = 1737.4;
const RELIEF_GAIN = 1.65;

/** Wektor ENU [N, E, U] z kontraktu → wektor sceny three.js (E, U, −N). */
export function enuToScene([n, e, u], out = new THREE.Vector3()) {
  return out.set(e, u, -n);
}

export function b64ToBytes(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const vertexShader = /* glsl */ `
  #include <common>
  #include <logdepthbuf_pars_vertex>
  attribute vec3 albedoRgb;
  flat varying vec3 vAlb;
  varying vec3 vWorld;
  void main() {
    vAlb = albedoRgb;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
    #include <logdepthbuf_vertex>
  }
`;

const fragmentShader = /* glsl */ `
  #include <logdepthbuf_pars_fragment>
  uniform vec3 uSunDir;          // kierunek do Słońca (scena)
  uniform float uSunEffVis;      // sun_effective_vis
  uniform float uEarthAlt;       // wysokość Ziemi [rad]
  uniform float uRedGlow;        // eclipse_red_glow
  uniform vec3 uMoonCenter;      // środek Księżyca w scenie (0, −observer_radius_km, 0)
  uniform float uAlbedoScale;
  uniform float uEdge;           // 1 = obrys siatki (tryb M): kolor + (35, 35, 40)
  flat varying vec3 vAlb;
  varying vec3 vWorld;
  void main() {
    #include <logdepthbuf_fragment>
    vec3 n = normalize(cross(dFdx(vWorld), dFdy(vWorld)));
    vec3 v = normalize(vWorld - uMoonCenter);
    if (dot(n, v) < 0.0) n = -n;
    float nv = dot(n, v);
    n = normalize(nv * v + ${RELIEF_GAIN.toFixed(2)} * (n - nv * v));

    float direct = pow(max(0.0, dot(n, uSunDir)), 0.85) * uSunEffVis;
    float earthshine = 0.045 * max(0.0, sin(uEarthAlt));
    float ambient = 0.032 + earthshine;
    float baseLight = 165.0 * ambient + 940.0 * direct;
    vec3 tint = vec3(1.0 + 0.85 * uRedGlow, 1.0 - 0.15 * uRedGlow, 1.0 - 0.35 * uRedGlow);
    vec3 alb = vAlb * uAlbedoScale;
    vec3 rgb = floor(clamp(alb * baseLight * tint, 5.0, 248.0));   // jak astype(np.int32) w pygame
    if (uEdge > 0.5) rgb = min(vec3(255.0), rgb + vec3(35.0, 35.0, 40.0));
    gl_FragColor = vec4(rgb / 255.0, 1.0);
  }
`;

function makeMaterial(uniforms, edge) {
  return new THREE.ShaderMaterial({
    uniforms: { ...uniforms, uEdge: { value: edge ? 1 : 0 } },
    vertexShader,
    fragmentShader,
    wireframe: edge,
    polygonOffset: !edge,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  });
}

/**
 * Buduje mesh z odpowiedzi lunar_surface.terrain.
 * Zwraca THREE.Group z userData.setLighting({...}) i userData.setWireframe(bool).
 */
export function buildTerrainMesh(patch) {
  const { n_r: nR, n_az: nAz, radii_km: radii, observer_radius_km: obsR } = patch;
  const eyeKm = patch.eye_height_m / 1000;
  const h = new Float32Array(b64ToBytes(patch.height_km_f32_b64).buffer);
  const alb = b64ToBytes(patch.albedo_rgb_u8_b64);

  const nVert = 1 + nR * nAz;
  const pos = new Float32Array(nVert * 3);
  const col = new Uint8Array(nVert * 3);
  // Wierzchołek środkowy: grunt pod okiem obserwatora.
  pos.set([0, -eyeKm, 0], 0);
  col.set(alb.subarray(0, 3), 0);
  const cosAz = new Float64Array(nAz);
  const sinAz = new Float64Array(nAz);
  for (let ia = 0; ia < nAz; ia++) {
    const az = (2 * Math.PI * ia) / nAz;
    cosAz[ia] = Math.cos(az);
    sinAz[ia] = Math.sin(az);
  }
  for (let ir = 0; ir < nR; ir++) {
    const delta = radii[ir] / R_MOON;
    const sd = Math.sin(delta);
    const cd = Math.cos(delta);
    for (let ia = 0; ia < nAz; ia++) {
      const k = ir * nAz + ia;
      const rad = R_MOON + h[k];
      const n = rad * sd * cosAz[ia];
      const e = rad * sd * sinAz[ia];
      const u = rad * cd - obsR;
      const o = (1 + k) * 3;
      pos[o] = e;
      pos[o + 1] = u;
      pos[o + 2] = -n;
      col[o] = alb[k * 3];
      col[o + 1] = alb[k * 3 + 1];
      col[o + 2] = alb[k * 3 + 2];
    }
  }

  // Trójkąty CCW patrząc z góry (normalne na zewnątrz Księżyca); azymut zawinięty.
  const index = new Uint32Array((nAz + (nR - 1) * nAz * 2) * 3);
  let p = 0;
  for (let ia = 0; ia < nAz; ia++) {
    const a = 1 + ia;
    const b = 1 + ((ia + 1) % nAz);
    index[p++] = 0; index[p++] = b; index[p++] = a;
  }
  for (let ir = 0; ir < nR - 1; ir++) {
    for (let ia = 0; ia < nAz; ia++) {
      const ib = (ia + 1) % nAz;
      const a = 1 + ir * nAz + ia;
      const b = 1 + ir * nAz + ib;
      const c = 1 + (ir + 1) * nAz + ia;
      const d = 1 + (ir + 1) * nAz + ib;
      index[p++] = a; index[p++] = b; index[p++] = c;
      index[p++] = b; index[p++] = d; index[p++] = c;
    }
  }

  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geom.setAttribute('albedoRgb', new THREE.BufferAttribute(col, 3, true));
  geom.setIndex(new THREE.BufferAttribute(index, 1));
  geom.computeBoundingSphere();

  const uniforms = {
    uSunDir: { value: new THREE.Vector3(0, 1, 0) },
    uSunEffVis: { value: 0 },
    uEarthAlt: { value: 0 },
    uRedGlow: { value: 0 },
    uMoonCenter: { value: new THREE.Vector3(0, -obsR, 0) },
    uAlbedoScale: { value: patch.albedo_scale },
  };
  const fill = new THREE.Mesh(geom, makeMaterial(uniforms, false));
  const edges = new THREE.Mesh(geom, makeMaterial(uniforms, true));
  edges.visible = false;
  fill.frustumCulled = false;
  edges.frustumCulled = false;

  const group = new THREE.Group();
  group.add(fill, edges);
  group.userData.triangles = index.length / 3;
  group.userData.setLighting = ({ sunDirScene, sunEffVis, earthAltRad, redGlow }) => {
    uniforms.uSunDir.value.copy(sunDirScene).normalize();
    uniforms.uSunEffVis.value = sunEffVis;
    uniforms.uEarthAlt.value = earthAltRad;
    uniforms.uRedGlow.value = redGlow;
  };
  group.userData.setWireframe = (on) => { edges.visible = on; };
  group.userData.dispose = () => {
    geom.dispose();
    fill.material.dispose();
    edges.material.dispose();
  };
  return group;
}
