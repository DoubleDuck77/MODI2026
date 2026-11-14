"""Kontrakt modułu ``horizon``: horyzont terenowy obserwatora na Księżycu i położenia Ziemi/Słońca na jego niebie."""

from datetime import datetime
from typing import List

from pydantic import Field, model_validator

from app.core.contracts import AltAz, Contract, FeatureResponse, SelenoPoint, Vec3


class HorizonProfile(Contract):
    """``elevation_deg[i]`` to elewacja horyzontu terenowego dla azymutu ``i · az_step_deg`` (N=0, E=90)."""

    az_step_deg: float = Field(gt=0, le=90)
    elevation_deg: List[float]

    @model_validator(mode="after")
    def _full_circle(self) -> "HorizonProfile":
        if abs(len(self.elevation_deg) * self.az_step_deg - 360) > 1e-6:
            raise ValueError(
                f"profil musi pokrywać 360°: {len(self.elevation_deg)} × {self.az_step_deg}° ≠ 360°"
            )
        return self


class LocalBasis(Contract):
    """Lokalne wersory obserwatora w układzie związanym z Księżycem."""

    north: Vec3
    east: Vec3
    up: Vec3


class HorizonView(FeatureResponse):
    t: datetime
    observer: SelenoPoint
    observer_elevation_m: float
    profile: HorizonProfile
    earth: AltAz
    sun: AltAz
    local_basis: LocalBasis
