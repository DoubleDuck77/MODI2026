// Panel warstw: checkbox na warstwę, pogrupowane po widoku.

const VIEW_LABELS = { space: 'Kosmos', surface: 'Powierzchnia Księżyca' };

export function renderLayerPanel(root, layers, onChange = () => {}) {
  root.replaceChildren();
  for (const view of Object.keys(VIEW_LABELS)) {
    const group = layers.filter((l) => l.feature.view === view);
    if (!group.length) continue;

    const fieldset = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = VIEW_LABELS[view];
    fieldset.append(legend);

    for (const layer of group) {
      const label = document.createElement('label');
      label.className = 'layer-toggle';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = layer.visible;
      input.addEventListener('change', () => {
        layer.setVisible(input.checked);
        onChange(layer);
      });
      const title = document.createElement('span');
      title.textContent = layer.feature.title;
      const id = document.createElement('code');
      id.textContent = layer.feature.id;
      label.append(input, title, id);
      fieldset.append(label);
    }
    root.append(fieldset);
  }
}
