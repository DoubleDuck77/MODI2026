"""Kontrakt modułu ``lunar_resources``: zasoby geochemiczne w promieniu R od punktu (``radius.py``).

Pola ``RoiRow`` mają te same nazwy i kolejność co słowniki z ``LunarDepositAnalyzer.query_roi``
(``radius.py:146-160``); wartości NaN idą jako ``null``.
"""

import math
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from app.core.contracts import Contract, FeatureResponse, ObserverFields

MAX_ROWS = 10


class RoiQuery(ObserverFields):
    """Punkt (lat, lon) + promień R; górna granica to połowa obwodu Księżyca (π·R_moon)."""

    radius_km: float = Field(250.0, gt=0, le=5458, description="Promień R [km] (great-circle)")


# --- Katalog ----------------------------------------------------------------------------


class SliderSpec(Contract):
    min: float
    max: float
    step: float
    init: float


class Sliders(Contract):
    lat_deg: SliderSpec
    lon_deg: SliderSpec
    radius_km: SliderSpec


class Defaults(Contract):
    lat_deg: float
    lon_deg: float
    radius_km: float


class ResourceLayer(Contract):
    key: str
    title: str
    unit: str
    cmap: str
    vmin: float
    vmax: float
    colormap_u8: List[Tuple[int, int, int]] = Field(description="Dokładnie 256 kolorów RGB cmapy matplotliba")
    global_mean: Optional[float] = None
    data_source: str
    image_url: str

    @model_validator(mode="after")
    def _colormap_256(self) -> "ResourceLayer":
        if len(self.colormap_u8) != 256:
            raise ValueError("colormap_u8 musi mieć dokładnie 256 kolorów")
        if any(not 0 <= c <= 255 for rgb in self.colormap_u8 for c in rgb):
            raise ValueError("składowe colormap_u8 muszą być w 0..255")
        return self


class ChartGroup(Contract):
    title: str
    unit: str
    keys: List[str]


class ResourceCatalog(FeatureResponse):
    map_width: int
    map_height: int
    r_moon_km: float
    layers: List[ResourceLayer]
    chart_groups: List[ChartGroup]
    defaults: Defaults
    sliders: Sliders


# --- ROI --------------------------------------------------------------------------------


class RoiSummary(Contract):
    lat_deg: float
    lon_deg: float
    radius_km: float
    cap_area_km2: float
    pixel_count: int


class RoiRow(Contract):
    resource_key: str
    resource_name: str
    unit: str
    latitude_deg: float
    longitude_deg: float
    radius_km: float
    surface_area_km2: float
    roi_weighted_mean: Optional[float]
    lunar_global_mean: Optional[float]
    diff_vs_global_pct: Optional[float]
    roi_min: Optional[float]
    roi_max: Optional[float]
    data_source: str


class ResourceRoi(FeatureResponse):
    roi: RoiSummary
    rows: List[RoiRow]
    contour_lonlat: List[List[Tuple[float, float]]]

    @model_validator(mode="after")
    def _checks(self) -> "ResourceRoi":
        if len(self.rows) > MAX_ROWS:
            raise ValueError(f"rows: najwyżej {MAX_ROWS} wierszy")
        if any(not (math.isfinite(x) and math.isfinite(y)) for line in self.contour_lonlat for x, y in line):
            raise ValueError("punkty konturu muszą być skończone")
        return self
