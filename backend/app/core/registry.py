"""Odkrywanie modułów i walidujący rejestr.

Rejestr sprawdza przy starcie wszystko, co da się sprawdzić bez uruchamiania obliczeń —
w tym zgodność każdego przykładu JSON z modelem odpowiedzi. Błąd = aplikacja nie startuje.
"""

import importlib
import pkgutil
import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ValidationError

from app.core.context import AppContext
from app.core.contracts import FeatureResponse, ObserverQuery, TimeDependency
from app.core.facade import BaseFacade, _read_bytes, example_path
from app.core.feature import Endpoint, FeatureModule

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class FeatureRegistryError(Exception):
    """Błąd konfiguracji modułu wykryty przy starcie."""


def discover_features(package: str = "app.features") -> List[FeatureModule]:
    """Importuje każdy podpakiet ``package`` (poza ``_*``) i zbiera jego ``FEATURE``."""
    pkg = importlib.import_module(package)
    found: List[FeatureModule] = []
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        feature = getattr(module, "FEATURE", None)
        if not isinstance(feature, FeatureModule):
            raise FeatureRegistryError(f"[{info.name}] pakiet {module.__name__} nie definiuje FEATURE: FeatureModule")
        if feature.id != info.name:
            raise FeatureRegistryError(f"[{feature.id}] id musi być równe nazwie pakietu '{info.name}'")
        found.append(feature)
    return sorted(found, key=lambda f: f.id)


class FeatureRegistry:
    def __init__(self, features: List[FeatureModule], ctx: AppContext) -> None:
        _read_bytes.cache_clear()
        self.ctx = ctx
        self._features: Dict[str, FeatureModule] = {}
        self._endpoints: Dict[str, Tuple[FeatureModule, Endpoint]] = {}
        self._facades: Dict[str, BaseFacade] = {}
        for feature in features:
            self._register(feature)

    # --- walidacja -----------------------------------------------------------------------

    def _register(self, feature: FeatureModule) -> None:
        fid = feature.id

        def fail(msg: str) -> None:
            raise FeatureRegistryError(f"[{fid}] {msg}")

        if fid in self._features:
            fail("zduplikowane id modułu")
        if not ID_RE.match(fid):
            fail(f"id musi pasować do {ID_RE.pattern}")
        if feature.facade.feature_id != fid:
            fail(f"{feature.facade.__name__}.feature_id = '{feature.facade.feature_id}', oczekiwano '{fid}'")

        names = set()
        for ep in feature.endpoints:
            if not ID_RE.match(ep.name):
                fail(f"nazwa endpointu '{ep.name}' musi pasować do {ID_RE.pattern}")
            if ep.name in names:
                fail(f"zduplikowany endpoint '{ep.name}'")
            names.add(ep.name)
            if not callable(getattr(feature.facade, ep.handler, None)):
                fail(f"{feature.facade.__name__} nie ma metody '{ep.handler}' (endpoint '{ep.name}')")
            if ep.time_dependency is TimeDependency.STATIC and ep.params is not None:
                fail(f"endpoint static '{ep.name}' nie może mieć parametrów")
            if ep.frame:
                if ep.time_dependency is not TimeDependency.TIME_DEPENDENT:
                    fail(f"endpoint frame '{ep.name}' musi być time_dependent")
                if ep.params is None:
                    fail(f"endpoint frame '{ep.name}' musi mieć parametry")
                extra = set(ep.params.model_fields) - set(ObserverQuery.model_fields)
                if extra:
                    fail(f"endpoint frame '{ep.name}' ma pola spoza ObserverQuery: {sorted(extra)}")
            self._check_example(feature, ep, fail)

        self._features[fid] = feature
        for ep in feature.endpoints:
            self._endpoints[feature.key(ep)] = (feature, ep)
        self._facades[fid] = feature.facade(self.ctx)

    def _check_example(self, feature: FeatureModule, ep: Endpoint, fail) -> None:
        path = example_path(self.ctx.settings.examples_dir, feature.id, ep.name)
        if not path.is_file():
            fail(f"brak przykładu kontraktu {path.name} (oczekiwany w {path.parent})")
        try:
            ep.response.model_validate_json(path.read_bytes())
        except ValidationError as e:
            fail(f"przykład {path.name} niezgodny z {ep.response.__name__}:\n{e}")

    # --- API rejestru --------------------------------------------------------------------

    def features(self) -> List[FeatureModule]:
        return list(self._features.values())

    def facade(self, feature_id: str) -> BaseFacade:
        return self._facades[feature_id]

    def endpoint(self, key: str) -> Tuple[FeatureModule, Endpoint]:
        return self._endpoints[key]

    def frame_keys(self) -> List[str]:
        return sorted(k for k, (_, ep) in self._endpoints.items() if ep.frame)

    def call(self, key: str, params: Optional[BaseModel]) -> FeatureResponse:
        feature, ep = self._endpoints[key]
        handler = getattr(self._facades[feature.id], ep.handler)
        return handler() if ep.params is None else handler(params)
