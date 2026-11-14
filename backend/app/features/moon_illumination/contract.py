"""Kontrakt modułu ``moon_illumination``: kierunek Słońca w układzie Księżyca, terminator i cienie obiektów."""

from datetime import datetime
from typing import List, Optional

from pydantic import Field, model_validator

from app.core.contracts import Contract, FeatureResponse, SelenoPoint, Vec3


class FeatureShadow(Contract):
    feature_id: str = Field(description="Id obiektu z moon_geography.features")
    sun_elevation_deg: float = Field(ge=-90, le=90, description="Wysokość Słońca nad horyzontem w środku obiektu")
    shadow_length_km: Optional[float] = Field(None, ge=0, description="None, gdy obiekt jest całkiem w cieniu")
    in_shadow: bool

    @model_validator(mode="after")
    def _consistent(self) -> "FeatureShadow":
        if self.in_shadow != (self.sun_elevation_deg <= 0):
            raise ValueError(f"[{self.feature_id}] in_shadow musi być równe (sun_elevation_deg <= 0)")
        if (self.shadow_length_km is None) != self.in_shadow:
            raise ValueError(f"[{self.feature_id}] shadow_length_km jest None wtedy i tylko wtedy, gdy in_shadow")
        return self


class MoonIllumination(FeatureResponse):
    """Wektory to wersory w układzie związanym z Księżycem (x → lon 0, y → lon 90°E, z → biegun N)."""

    t: datetime
    sun_dir_body: Vec3
    earth_dir_body: Vec3
    subsolar_point: SelenoPoint
    sub_earth_point: SelenoPoint = Field(description="Środek tarczy widzianej z Ziemi (libracja)")
    terminator: List[SelenoPoint] = Field(min_length=3)
    shadows: List[FeatureShadow]
