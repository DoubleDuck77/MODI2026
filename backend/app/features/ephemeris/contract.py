"""Kontrakt modułu ``ephemeris``: położenia Słońca i Księżyca oraz ich korelacja (faza, elongacja)."""

from datetime import datetime
from typing import List, Literal, Tuple

from pydantic import Field, model_validator

from app.core.contracts import Contract, FeatureResponse, Vec3

MoonPhaseName = Literal[
    "new",
    "waxing_crescent",
    "first_quarter",
    "waxing_gibbous",
    "full",
    "waning_gibbous",
    "last_quarter",
    "waning_crescent",
]


class MoonPhase(Contract):
    phase_angle_deg: float = Field(ge=0, le=180, description="Kąt Słońce–Księżyc–Ziemia")
    illuminated_fraction: float = Field(ge=0, le=1)
    waxing: bool
    name: MoonPhaseName


class EphemerisState(FeatureResponse):
    """Stan układu w chwili ``t``. Wektory geocentryczne, ekliptyka J2000, km."""

    t: datetime
    sun_km: Vec3
    moon_km: Vec3
    earth_moon_distance_km: float = Field(gt=0)
    earth_sun_distance_km: float = Field(gt=0)
    elongation_deg: float = Field(ge=0, le=180, description="Kąt Słońce–Ziemia–Księżyc")
    moon_phase: MoonPhase
    earth_illuminated_fraction_from_moon: float = Field(ge=0, le=1)


Triple = Tuple[float, float, float]


class EphemerisSeries(FeatureResponse):
    """Szereg czasowy w formacie kolumnowym: punkt ``i`` to chwila ``start + i·step_hours``."""

    start: datetime
    step_hours: int = Field(ge=1)
    sun_km: List[Triple]
    moon_km: List[Triple]

    @model_validator(mode="after")
    def _same_length(self) -> "EphemerisSeries":
        if not self.sun_km or len(self.sun_km) != len(self.moon_km):
            raise ValueError("sun_km i moon_km muszą być niepuste i mieć tę samą długość")
        return self
