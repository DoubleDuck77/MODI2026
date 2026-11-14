"""Kontrakt modułu ``lunar_orbit``: symulator orbit wokół Księżyca z ``neworb.py``.

Układ: związany z Księżycem (``MOON_BODY_FIXED``: x = lon 0, y = 90°E, z = biegun N), km i s.
Prędkości ``vel_kms`` są w układzie obracającym się z Księżycem — dokładnie jak ``state[3:]``
w ``neworb.py`` (``speed_kms`` to prędkość inercjalna, jak w telemetrii neworb).
"""

import math
from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from app.core.contracts import MAX_SERIES_POINTS, Contract, FeatureResponse, TimeQuery

Vec3T = Tuple[float, float, float]


class OrbitPresetId(str, Enum):
    LRO = "LRO"
    GATEWAY = "Gateway"
    LUNA10 = "Luna 10"
    APOLLO_PFS2 = "Apollo PFS-2"
    CUSTOM = "CUSTOM"


# --- Zapytania ---------------------------------------------------------------------------


class OrbitInitialQuery(TimeQuery):
    preset: OrbitPresetId
    altitude_km: float = Field(100.0, ge=1, le=100000, description="Tylko CUSTOM")
    inclination_deg: float = Field(45.0, ge=0, le=180, description="Tylko CUSTOM")
    speed_kms: Optional[float] = Field(None, gt=0, le=10, description="Tylko CUSTOM; brak = prędkość kołowa")


class OrbitPropagateQuery(TimeQuery):
    x_km: float
    y_km: float
    z_km: float
    vx_kms: float
    vy_kms: float
    vz_kms: float
    duration_s: float = Field(ge=1, le=345600)
    sample_dt_s: float = Field(ge=1, le=86400)
    use_mascons: bool = True
    third_body: bool = True

    @model_validator(mode="after")
    def _limit(self) -> "OrbitPropagateQuery":
        n = math.ceil(self.duration_s / self.sample_dt_s) + 1
        if n > MAX_SERIES_POINTS:
            raise ValueError(f"zakres daje {n} próbek, maksimum to {MAX_SERIES_POINTS}")
        return self


# --- Odpowiedzi --------------------------------------------------------------------------


class OrbitPreset(Contract):
    id: OrbitPresetId
    label: str


class CustomOrbitDefaults(Contract):
    altitude_km: float
    inclination_deg: float
    speed_kms: float


class Mascon(Contract):
    name: str
    lat_deg: float
    lon_deg: float
    depth_km: float
    core_radius_km: float
    delta_mu_km3_s2: float


class Landmark(Contract):
    name: str
    lat_deg: float
    lon_deg: float
    kind: str
    color_rgb: Tuple[int, int, int]


class OrbitCatalog(FeatureResponse):
    r_moon_km: float
    gm_moon_km3_s2: float
    omega_moon_rad_s: float
    r_escape_km: float
    max_step_s: float
    presets: List[OrbitPreset]
    custom_defaults: CustomOrbitDefaults
    mascons: List[Mascon]
    landmarks: List[Landmark]


class OrbitState(FeatureResponse):
    t: datetime
    preset: OrbitPresetId
    pos_km: Vec3T
    vel_kms: Vec3T


TrackStatus = Literal["ok", "crash", "escape", "nan", "ephemeris_end"]


class OrbitTrack(FeatureResponse):
    t: datetime = Field(description="Czas pierwszej próbki (= t zapytania)")
    use_mascons: bool
    third_body: bool
    status: TrackStatus
    status_message: Optional[str] = None
    t_offset_s: List[float]
    pos_km: List[Vec3T]
    vel_kms: List[Vec3T]
    sun_body_km: List[Vec3T]
    earth_body_km: List[Vec3T]
    altitude_km: List[float]
    speed_kms: List[float]
    periapsis_km: List[float]
    apoapsis_km: List[Optional[float]] = Field(description="None = orbita niezwiązana (inf w neworb)")
    eccentricity: List[float]
    inclination_deg: List[float]
    mascon_dg_radial_mgal: List[float]
    mascon_dg_horiz_mgal: List[float]
    nearest_mascon: List[Optional[str]]

    @model_validator(mode="after")
    def _columns(self) -> "OrbitTrack":
        cols = ("pos_km", "vel_kms", "sun_body_km", "earth_body_km", "altitude_km", "speed_kms",
                "periapsis_km", "apoapsis_km", "eccentricity", "inclination_deg",
                "mascon_dg_radial_mgal", "mascon_dg_horiz_mgal", "nearest_mascon")
        n = len(self.t_offset_s)
        if n == 0:
            raise ValueError("ślad musi mieć co najmniej jedną próbkę")
        bad = [c for c in cols if len(getattr(self, c)) != n]
        if bad:
            raise ValueError(f"kolumny o złej długości (oczekiwano {n}): {bad}")
        return self
