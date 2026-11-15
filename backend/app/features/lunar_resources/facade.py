"""Fasada ``lunar_resources``: adapter na ``radius.py`` i ``generator.py`` (tylko import, bez zmian).

Budowa w wątku-demonie przy starcie (jak rozgrzewka JIT w ``lunar_orbit``): albedo bazowe
(``generator.load_base_albedo``), rastry zasobów z lokalnego katalogu PDS
(``generator.collect_resource_grids``), ``LunarDepositAnalyzer`` oraz nakładki RGB warstw
(``radius.py:195-206``). Serwer nie chodzi do sieci: ``discover_and_download_pds_files`` nie jest
wołane, a brak plików PDS daje 503 z listą. Do końca budowy endpointy odpowiadają 503 z
``Retry-After``.
"""

import io
import logging
import math
import threading
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, HTTPException, Response

from app.core.contracts import CONTRACT_VERSION, ReferenceFrame, ResponseMeta
from app.core.facade import BaseFacade
from app.core.legacy import import_root_script
from app.features.lunar_resources.contract import (
    ChartGroup,
    Defaults,
    ResourceCatalog,
    ResourceLayer,
    ResourceRoi,
    RoiQuery,
    RoiRow,
    RoiSummary,
    SliderSpec,
    Sliders,
)

log = logging.getLogger("uvicorn.error")

BASE_IMAGE = "moon_color.jpg"
LAYER_URL = "/api/v1/lunar_resources/layers/{key}.png"
LAYER_CACHE_CONTROL = "public, max-age=86400"
RETRY_AFTER_S = "5"
# Wartości początkowe i zakresy suwaków: radius.py:256-258 oraz argumenty domyślne :183-190.
DEFAULTS = Defaults(lat_deg=20.0, lon_deg=-25.0, radius_km=250.0)
SLIDERS = Sliders(
    lat_deg=SliderSpec(min=-90.0, max=90.0, step=0.5, init=20.0),
    lon_deg=SliderSpec(min=-180.0, max=180.0, step=0.5, init=-25.0),
    radius_km=SliderSpec(min=10.0, max=1000.0, step=5.0, init=250.0),
)


def _opt(x: float) -> Optional[float]:
    """NaN/Inf → ``None`` (JSON nie ma NaN)."""
    x = float(x)
    return x if math.isfinite(x) else None


class LunarResourcesFacade(BaseFacade):
    feature_id = "lunar_resources"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.gen = import_root_script("generator", ctx.settings.scripts_dir)
        self.rad = import_root_script("radius", ctx.settings.scripts_dir)
        self.analyzer = None
        self._png: Dict[str, bytes] = {}
        self._ranges: Dict[str, Tuple[float, float]] = {}
        self._ready = threading.Event()
        self._error: Optional[str] = None
        threading.Thread(target=self._build, name="lunar-resources-build", daemon=True).start()

    # --- budowa --------------------------------------------------------------------------

    def _build(self) -> None:
        t0 = time.perf_counter()
        try:
            from PIL import Image
            import matplotlib.pyplot as plt

            gen, rad, st = self.gen, self.rad, self.ctx.settings
            missing = sorted(n for n in gen.PDS_FILE_CATALOG if not (st.pds_data_dir / n).is_file())
            if missing:
                raise RuntimeError(f"PDS files missing in {st.pds_data_dir}: {', '.join(missing)}")
            if not (st.textures_dir / BASE_IMAGE).exists():
                raise FileNotFoundError(f"Base image not found: {st.textures_dir / BASE_IMAGE}")
            gray, w, h = gen.load_base_albedo(st.textures_dir / BASE_IMAGE)
            resources = gen.collect_resource_grids(st.pds_data_dir, gray)
            analyzer = rad.LunarDepositAnalyzer(resources, w, h)

            # Nakładki warstw: radius.py:195-206.
            spec_map = {k: (title, unit, cmap) for k, title, unit, cmap in rad.ENGLISH_RESOURCE_SPECS}
            shade = 0.42 + 0.58 * gray[:, :, None]
            png: Dict[str, bytes] = {}
            ranges: Dict[str, Tuple[float, float]] = {}
            for k in (k for k in rad.MAP_LAYER_KEYS if k in analyzer.resources):
                grid, _, _ = analyzer.resources[k]
                cmap_name = spec_map[k][2]
                vmin, vmax = np.nanpercentile(grid, [2, 98])
                if np.isclose(vmin, vmax):
                    vmin, vmax = float(np.nanmin(grid)), float(np.nanmax(grid) + 1e-6)
                norm = np.clip((grid - vmin) / (vmax - vmin + 1e-9), 0.0, 1.0)
                rgba = plt.get_cmap(cmap_name)(norm)
                rgb = np.clip(rgba[:, :, :3] * shade, 0.0, 1.0)
                buf = io.BytesIO()
                Image.fromarray(np.round(rgb * 255.0).astype(np.uint8), "RGB").save(buf, format="PNG")
                png[k] = buf.getvalue()
                ranges[k] = (float(vmin), float(vmax))
            self._png, self._ranges, self.analyzer = png, ranges, analyzer
            log.info("[lunar_resources] gotowe w %.1f s", time.perf_counter() - t0)
        except Exception as e:  # zgłaszane jako 503 z treścią
            log.exception("[lunar_resources] budowa nie powiodła się")
            self._error = f"{type(e).__name__}: {e}"
        finally:
            self._ready.set()

    def _require(self) -> None:
        if not self._ready.is_set():
            raise HTTPException(503, "lunar_resources: data is still being built, try again shortly",
                                headers={"Retry-After": RETRY_AFTER_S})
        if self._error:
            raise HTTPException(503, f"lunar_resources unavailable: {self._error}")

    def _meta(self, endpoint: str) -> ResponseMeta:
        return ResponseMeta(
            feature=self.feature_id, endpoint=endpoint, contract_version=CONTRACT_VERSION,
            source="computed", frame=ReferenceFrame.MOON_BODY_FIXED,
            units={"angle": "deg", "distance": "km", "area": "km2", "concentration": "wt. % / ppm"},
        )

    # --- endpointy -----------------------------------------------------------------------

    def catalog(self) -> ResourceCatalog:
        self._require()
        import matplotlib.pyplot as plt

        rad, an = self.rad, self.analyzer
        spec_map = {k: (title, unit, cmap) for k, title, unit, cmap in rad.ENGLISH_RESOURCE_SPECS}
        layers: List[ResourceLayer] = []
        for k in self._png:
            title, unit, cmap_name = spec_map[k]
            cmap = plt.get_cmap(cmap_name)
            lut = np.round(cmap(np.arange(cmap.N))[:, :3] * 255.0).astype(int)
            vmin, vmax = self._ranges[k]
            layers.append(ResourceLayer(
                key=k, title=title, unit=unit, cmap=cmap_name, vmin=vmin, vmax=vmax,
                colormap_u8=[tuple(int(c) for c in rgb) for rgb in lut],
                global_mean=_opt(an.global_means.get(k, float("nan"))),
                data_source=an.resources[k][1], image_url=LAYER_URL.format(key=k),
            ))
        return ResourceCatalog(
            meta=self._meta("catalog"), map_width=an.width, map_height=an.height,
            r_moon_km=rad.R_MOON_KM, layers=layers,
            chart_groups=[ChartGroup(title=t, unit=u, keys=list(ks)) for t, u, ks in rad.CHART_GROUPS],
            defaults=DEFAULTS, sliders=SLIDERS,
        )

    def roi(self, q: RoiQuery) -> ResourceRoi:
        self._require()
        import matplotlib as mpl
        import contourpy

        an = self.analyzer
        summary, rows = an.query_roi(q.lat_deg, q.lon_deg, q.radius_km)

        # Kontur jak ax_map.contour w radius.py:307-316 (ten sam generator contourpy co matplotlib).
        contour: List[List[Tuple[float, float]]] = []
        dist = an.spherical_distance_km(q.lat_deg, q.lon_deg)
        if np.nanmin(dist) < q.radius_km < np.nanmax(dist):
            gen = contourpy.contour_generator(
                x=an.lon_grid, y=an.lat_grid, z=dist,
                name=mpl.rcParams["contour.algorithm"], corner_mask=mpl.rcParams["contour.corner_mask"],
            )
            lines, _codes = gen.lines(q.radius_km)   # mpl2014 → SeparateCode: (punkty, kody ścieżki)
            contour = [[(float(x), float(y)) for x, y in line] for line in lines]

        return ResourceRoi(
            meta=self._meta("roi"),
            roi=RoiSummary(**summary),
            rows=[RoiRow(**{k: (_opt(v) if isinstance(v, float) else v) for k, v in r.items()}) for r in rows],
            contour_lonlat=contour,
        )

    def layer_png(self, key: str) -> bytes:
        self._require()
        data = self._png.get(key)
        if data is None:
            raise HTTPException(404, f"Unknown layer: {key}")
        return data


def layer_routes(facade: LunarResourcesFacade) -> APIRouter:
    """Trasa binarna nakładek: ``GET /api/v1/lunar_resources/layers/{key}.png``."""
    router = APIRouter()

    @router.get("/layers/{key}.png", summary="Nakładka RGB 1024×512 warstwy zasobu (PNG)")
    def layer(key: str) -> Response:
        return Response(content=facade.layer_png(key), media_type="image/png",
                        headers={"Cache-Control": LAYER_CACHE_CONTROL})

    return router
