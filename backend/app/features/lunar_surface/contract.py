"""Kontrakt modułu ``lunar_surface``: widok z powierzchni Księżyca z ``geografia.py``.

Wektory ``*_enu`` są w lokalnej bazie obserwatora w kolejności **[N, E, U]** — dokładnie jak
w ``get_topocentric_vectors`` (``obs_bases = (north, east, up)``). Teren rysuje przeglądarka
(WebGL2); serwer podaje geometrię obserwatora, niebo i kafle DEM/albedo.
"""

import math
from datetime import datetime
from typing import List, Literal, Tuple

from pydantic import BaseModel, Field, model_validator

from app.core.contracts import Contract, FeatureResponse, ObserverFields, SelenoPoint, TimeQuery

Vec3T = Tuple[float, float, float]


class EyeHeightField(BaseModel):
    eye_height_m: float = Field(15.0, ge=2, le=50000, description="Wysokość oka nad gruntem (suwak geografii 2–50000 m)")


class SurfaceQuery(TimeQuery, ObserverFields, EyeHeightField):
    """Czas + obserwator + wysokość oka."""


class ObserverGeometryQuery(ObserverFields, EyeHeightField):
    """Obserwator + wysokość oka (geometria terenu nie zależy od czasu)."""


# --- Niebo ------------------------------------------------------------------------------


class SkyBody(Contract):
    alt_deg: float
    az_deg: float
    distance_km: float
    angular_radius_deg: float
    horizon_alt_deg: float = Field(description="Wysokość horyzontu terenowego w azymucie ciała")
    dir_enu: Vec3T


class EarthInSky(SkyBody):
    visible: bool
    status: str


class SunInSky(SkyBody):
    horizon_visible_fraction: float
    eclipse_occultation: float
    effective_visibility: float
    status: str


class LunarSky(FeatureResponse):
    t: datetime
    observer: SelenoPoint
    eye_height_m: float
    observer_elevation_m: float
    observer_radius_km: float
    earth: EarthInSky
    sun: SunInSky
    eclipse_ring_factor: float
    eclipse_red_glow: float
    dark_side_exposure: float
    sun_from_earth_enu: Vec3T
    moon_from_earth_enu_km: Vec3T
    sun_distance_from_earth_km: float
    earth_axes_enu: Tuple[Vec3T, Vec3T, Vec3T] = Field(description="Osie X, Y, Z układu ECEF Ziemi w ENU obserwatora")
    ecliptic_to_enu: Tuple[Vec3T, Vec3T, Vec3T] = Field(description="Wiersze N, E, U: v_enu = M · v_ekliptyka_J2000")


class StarField(FeatureResponse):
    """Gwiazdy tła geografii (losowe, seed 42): kierunki w ekliptyce J2000 i jasność 90..254."""

    ecliptic_xyz: List[Vec3T]
    brightness: List[int]

    @model_validator(mode="after")
    def _same_length(self) -> "StarField":
        if len(self.ecliptic_xyz) != len(self.brightness):
            raise ValueError("ecliptic_xyz i brightness muszą mieć tę samą długość")
        return self


# --- Teren ------------------------------------------------------------------------------


class HorizonProfile(Contract):
    az_deg: List[float]
    alt_deg: List[float]
    distance_km: List[float]
    lat_deg: List[float]
    lon_deg: List[float]
    elevation_km: List[float]


class TileSetInfo(Contract):
    """Opis zestawu kafli (siatka ``nx`` × ``ny`` kafli ``tile_w`` × ``tile_h`` px)."""

    width: int = Field(gt=0, description="Szerokość całej mapy [px]")
    height: int = Field(gt=0, description="Wysokość całej mapy [px]")
    tile_w: int = Field(gt=0)
    tile_h: int = Field(gt=0)
    nx: int = Field(gt=0)
    ny: int = Field(gt=0)
    dtype: Literal["float32", "uint8"]
    channels: int = Field(gt=0)
    url_template: str = Field(description="Szablon URL kafla z polami {ty} i {tx}; wiersz 0 to północ")


class SurfaceCatalog(FeatureResponse):
    """Stałe terenu i LOD z ``geografia.LunarTerrain3D`` oraz opis kafli DEM/albedo."""

    r_moon_km: float
    dem_source: str
    dem: TileSetInfo
    albedo: TileSetInfo
    albedo_is_u8: bool
    albedo_scale: float = Field(gt=0, description="Skala albedo jak w _init_gpu: 1.0 dla uint8, 0.40 dla float")
    patch_n: int
    tau_px: float
    max_patches: int
    min_cell_scale: float


class ObserverGeometry(FeatureResponse):
    """Wynik ``LunarTerrain3D.update_observer``: grunt, nachylenie i profil horyzontu."""

    observer: SelenoPoint
    eye_height_m: float
    observer_elevation_km: float
    observer_radius_km: float
    r_max_km: float
    slope_deg: float
    slope_dir: str = Field(description='"Flat" lub kierunek spadku (N, NE, ..., NW)')
    horizon: HorizonProfile

    @model_validator(mode="after")
    def _finite(self) -> "ObserverGeometry":
        nums = [self.eye_height_m, self.observer_elevation_km, self.observer_radius_km,
                self.r_max_km, self.slope_deg]
        h = self.horizon
        for f in HorizonProfile.model_fields:
            nums.extend(getattr(h, f))
        if not all(math.isfinite(x) for x in nums):
            raise ValueError("geometria obserwatora musi składać się ze skończonych liczb")
        n = len(h.az_deg)
        if any(len(getattr(h, f)) != n for f in HorizonProfile.model_fields):
            raise ValueError("profil horyzontu musi mieć tyle samo wartości w każdej kolumnie")
        return self
