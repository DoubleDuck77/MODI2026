"""Kontrakt modułu ``line_of_sight``: czy obserwator na Księżycu widzi Ziemię i kiedy."""

from datetime import datetime
from typing import List, Optional

from pydantic import Field, model_validator

from app.core.contracts import AltAz, Contract, FeatureResponse, SelenoPoint


class LineOfSight(FeatureResponse):
    t: datetime
    observer: SelenoPoint
    earth: AltAz
    horizon_elevation_deg: float = Field(description="Elewacja horyzontu terenowego w azymucie Ziemi")
    clearance_deg: float = Field(description="earth.alt_deg − horizon_elevation_deg")
    visible_disk_fraction: float = Field(ge=0, le=1)
    earth_visible: bool
    blocked_by: Optional[str] = Field(None, description="Id obiektu z moon_geography zasłaniającego Ziemię")

    @model_validator(mode="after")
    def _consistent(self) -> "LineOfSight":
        if abs(self.clearance_deg - (self.earth.alt_deg - self.horizon_elevation_deg)) > 1e-6:
            raise ValueError("clearance_deg musi być równe earth.alt_deg − horizon_elevation_deg")
        if self.earth_visible != (self.visible_disk_fraction > 0):
            raise ValueError("earth_visible musi być równe (visible_disk_fraction > 0)")
        return self


class VisibilityWindow(Contract):
    start: datetime
    end: datetime
    max_clearance_deg: float

    @model_validator(mode="after")
    def _ordered(self) -> "VisibilityWindow":
        if self.start >= self.end:
            raise ValueError("okno: start musi być wcześniejszy niż end")
        return self


class VisibilityWindows(FeatureResponse):
    observer: SelenoPoint
    start: datetime
    end: datetime
    step_hours: int = Field(ge=1)
    windows: List[VisibilityWindow]
    visible_fraction: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sorted_disjoint_inside(self) -> "VisibilityWindows":
        prev_end = self.start
        for w in self.windows:
            if w.start < prev_end:
                raise ValueError("okna muszą być posortowane, rozłączne i zaczynać się nie wcześniej niż start")
            prev_end = w.end
        if prev_end > self.end:
            raise ValueError("okna nie mogą wychodzić poza end")
        return self
