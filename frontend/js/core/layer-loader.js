// Ładuje warstwy wskazane w manifeście. Błąd jednej warstwy nie zatrzymuje pozostałych.

export async function loadLayers(manifest, ctx) {
  const layers = await Promise.all(manifest.features.map(async (feature) => {
    try {
      const mod = await import(feature.frontend_module);
      const Layer = mod.default;
      if (typeof Layer !== 'function') {
        throw new Error(`${feature.frontend_module} nie eksportuje domyślnie klasy warstwy`);
      }
      if (Layer.id !== feature.id) throw new Error(`static id = '${Layer.id}', manifest oczekuje '${feature.id}'`);
      if (Layer.view !== feature.view) throw new Error(`static view = '${Layer.view}', manifest oczekuje '${feature.view}'`);
      const layer = new Layer({ ...ctx, feature });
      await layer.init();
      ctx.scene.views[feature.view].add(layer.group);
      return layer;
    } catch (err) {
      console.error(`[layer-loader] ${feature.id}:`, err);
      ctx.inspector.error(feature.id, `Nie udało się załadować warstwy: ${err?.message ?? err}`);
      return null;
    }
  }));
  return layers.filter(Boolean);
}
