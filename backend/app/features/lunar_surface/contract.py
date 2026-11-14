"""Kontrakt modułu ``lunar_surface``: widok z powierzchni Księżyca z ``newlunar.py``.

Wektory ``*_enu`` są w lokalnej bazie obserwatora w kolejności **[N, E, U]** — dokładnie jak
w ``newlunar.get_topocentric_vectors`` (``obs_bases = (north, east, up)``). Frontend mapuje je
na three.js jako N = −Z, E = +X, U = +Y.
"""

import base64
from datetime import datetime
from typing import List, Tuple

from pydantic import BaseModel, Field, model_validator

from app.core.contracts import Contract, FeatureResponse, ObserverFields, SelenoPoint, TimeQuery

Vec3T = Tuple[float, float, float]


class EyeHeightField(BaseModel):
    eye_height_m: float = Field(2.0, ge=2, le=50000, description="Wysokość oka nad gruntem (suwak newlunar 2–50000 m)")


class SurfaceQuery(TimeQuery, ObserverFields, EyeHeightField):
    """Czas + obserwator + wysokość oka."""


class TerrainQuery(ObserverFields, EyeHeightField):
    """Obserwator + wysokość oka (teren nie zależy od czasu)."""


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
    earth_axes_enu: Tuple[Vec3T, Vec3T, Vec3T] = Field(description="Osie X, Y, Z układu ECEF Ziemi w ENU obserwatora")
    ecliptic_to_enu: Tuple[Vec3T, Vec3T, Vec3T] = Field(description="Wiersze N, E, U: v_enu = M · v_ekliptyka_J2000")


# --- Teren ------------------------------------------------------------------------------


class HorizonProfile(Contract):
    az_deg: List[float]
    alt_deg: List[float]
    distance_km: List[float]
    lat_deg: List[float]
    lon_deg: List[float]
    elevation_km: List[float]


def _b64_len(s: str) -> int:
    return len(base64.b64decode(s, validate=True))


class LunarTerrainPatch(FeatureResponse):
    observer: SelenoPoint
    eye_height_m: float
    observer_elevation_m: float
    observer_radius_km: float
    r_max_km: float
    dem_source: str
    window_sub: int
    n_az: int = Field(gt=0)
    n_r: int = Field(gt=0)
    az_step_deg: float
    radii_km: List[float]
    height_km_f32_b64: str = Field(description="float32 LE, kształt (n_r, n_az), wysokość względem R_MOON [km]")
    albedo_rgb_u8_b64: str = Field(description="uint8, kształt (n_r, n_az, 3): albedo = u8/255 · albedo_scale")
    albedo_scale: float = Field(gt=0, description="Albedo po LUT newlunar (0.055..0.275) zakodowane jako u8/255·scale")
    horizon: HorizonProfile

    @model_validator(mode="after")
    def _shapes(self) -> "LunarTerrainPatch":
        n = self.n_r * self.n_az
        if len(self.radii_km) != self.n_r:
            raise ValueError("radii_km musi mieć n_r wartości")
        if _b64_len(self.height_km_f32_b64) != 4 * n:
            raise ValueError("height_km_f32_b64 musi mieć n_r·n_az wartości float32")
        if _b64_len(self.albedo_rgb_u8_b64) != 3 * n:
            raise ValueError("albedo_rgb_u8_b64 musi mieć n_r·n_az·3 bajtów")
        h = self.horizon
        if any(len(getattr(h, f)) != self.n_az for f in HorizonProfile.model_fields):
            raise ValueError("profil horyzontu musi mieć n_az wartości w każdej kolumnie")
        return self
