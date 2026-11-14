"""Kontrakt modułu ``lagrange``: punkty L1–L5 układu Ziemia–Księżyc."""

from datetime import datetime
from typing import List, Literal

from pydantic import Field, model_validator

from app.core.contracts import Contract, FeatureResponse, Vec3

LagrangeId = Literal["L1", "L2", "L3", "L4", "L5"]
LAGRANGE_IDS = ["L1", "L2", "L3", "L4", "L5"]


class LagrangePoint(Contract):
    id: LagrangeId
    position_km: Vec3 = Field(description="Geocentrycznie, ekliptyka J2000")
    position_rotating: Vec3 = Field(
        description="Układ rotujący: środek w barycentrum, jednostka = odległość Ziemia–Księżyc"
    )
    distance_from_earth_km: float = Field(ge=0)
    distance_from_moon_km: float = Field(ge=0)
    stable: bool


class RotatingFrame(Contract):
    """Wersory układu rotującego wyrażone w ekliptyce J2000 (x → Księżyc, z → normalna orbity)."""

    origin: Literal["earth_moon_barycenter"]
    x_axis: Vec3
    y_axis: Vec3
    z_axis: Vec3


class LagrangePoints(FeatureResponse):
    t: datetime
    mass_ratio: float = Field(gt=0, lt=0.5, description="μ = m_K / (m_Z + m_K)")
    earth_moon_distance_km: float = Field(gt=0)
    rotating_frame: RotatingFrame
    points: List[LagrangePoint]

    @model_validator(mode="after")
    def _all_points_in_order(self) -> "LagrangePoints":
        if [p.id for p in self.points] != LAGRANGE_IDS:
            raise ValueError(f"points muszą zawierać dokładnie {LAGRANGE_IDS} w tej kolejności")
        return self
