// Bootstrap aplikacji: manifest → scena → warstwy → dane static → planista /frame → UI → pętla.

import { ApiClient } from './core/api-client.js';
import { SimulationClock } from './core/clock.js';
import { FrameScheduler } from './core/frame-scheduler.js';
import { loadLayers } from './core/layer-loader.js';
import { ObserverState } from './core/observer.js';
import { SceneContext } from './core/scene.js';
import { bindControls } from './ui/controls.js';
import { Inspector } from './ui/inspector.js';
import { renderLayerPanel } from './ui/layer-panel.js';

async function bootstrap() {
  const inspector = new Inspector(document.getElementById('inspector'));
  const api = new ApiClient('/api/v1');

  let manifest;
  try {
    manifest = await api.manifest();
  } catch (err) {
    inspector.error('manifest', `Brak połączenia z API: ${err?.message ?? err}`);
    return;
  }

  const scene = new SceneContext(document.getElementById('viewport'));
  const clock = new SimulationClock();
  const observer = new ObserverState();
  const layers = await loadLayers(manifest, { api, scene, clock, observer, inspector });

  const layerByKey = new Map();
  for (const layer of layers) for (const ep of layer.feature.endpoints) layerByKey.set(ep.key, layer);

  // Dane static: raz na start, z cache klienta.
  await Promise.allSettled(layers.flatMap((layer) => layer.feature.endpoints
    .filter((ep) => ep.time_dependency === 'static')
    .map((ep) => api.getJson(ep.path, {}, { cache: true }).then(
      (payload) => layer.onData(ep.key, payload),
      (err) => inspector.error(ep.key, err?.message ?? String(err)),
    ))));

  // Dane zależne od czasu: jedno zapytanie /frame dla wszystkich widocznych warstw.
  const scheduler = new FrameScheduler({
    api, clock, observer,
    getActiveKeys: () => layers.filter((l) => l.visible).flatMap((l) => l.frameKeys()),
    dispatch: (key, payload) => layerByKey.get(key)?.onData(key, payload),
    onError: (key, message) => inspector.error(key, message),
  });
  scheduler.start();
  scheduler.refresh('init');

  bindControls({ clock, observer, scene });
  renderLayerPanel(document.getElementById('layer-panel'), layers, () => scheduler.refresh('layers'));

  scene.onFrame((dt) => {
    clock.tick(dt);
    for (const layer of layers) if (layer.visible) layer.update(clock.t, dt);
  });
  scene.start();

  // Uchwyt do debugowania w konsoli przeglądarki.
  window.modi = { api, scene, clock, observer, layers, scheduler, manifest };
}

bootstrap();
