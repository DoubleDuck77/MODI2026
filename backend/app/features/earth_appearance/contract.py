"""Kontrakt modułu ``earth_appearance``: rotacja Ziemi, niezależnie dryfujące chmury i światła miast po stronie nocnej."""

from datetime import datetime
from typing import List

from pydantic import Field, model_validator

from app.core.contracts import AssetRef, Contract, FeatureResponse, GeoPoint


class BodyRotation(Contract):
    angle_deg: float = Field(ge=0, lt=360, description="Kąt obrotu południka zerowego (z GMST)")
    rate_deg_per_hour: float = Field(gt=0)


class CloudLayer(Contract):
    """Osobna sfera chmur: obraca się własnym kątem, niezależnie od ``rotation``."""

    texture: AssetRef
    angle_deg: float = Field(ge=0, lt=360)
    rate_deg_per_hour: float
    altitude_km: float = Field(gt=0)


class CityLight(Contract):
    name: str
    location: GeoPoint
    sun_elevation_deg: float = Field(ge=-90, le=90)
    lights_on: bool


class CityLights(Contract):
    """Shader: światła pełne przy elewacji Słońca ≤ ``on_below_sun_elevation_deg``, zero przy
    ≥ ``on_below_sun_elevation_deg + fade_deg``, liniowo pomiędzy. ``cities`` służą do znaczników/etykiet."""

    on_below_sun_elevation_deg: float
    fade_deg: float = Field(gt=0)
    cities: List[CityLight]

    @model_validator(mode="after")
    def _switch_rule(self) -> "CityLights":
        for c in self.cities:
            if c.lights_on != (c.sun_elevation_deg <= self.on_below_sun_elevation_deg):
                raise ValueError(
                    f"[{c.name}] lights_on musi być równe (sun_elevation_deg <= {self.on_below_sun_elevation_deg})"
                )
        return self


class EarthAppearance(FeatureResponse):
    t: datetime
    axial_tilt_deg: float
    rotation: BodyRotation
    clouds: CloudLayer
    subsolar_point: GeoPoint
    day_texture: AssetRef
    night_texture: AssetRef
    city_lights: CityLights
