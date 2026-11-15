"""Wspólne kontrakty wszystkich modułów.

Zasady:
- modele odpowiedzi dziedziczą ``Contract`` (``extra="forbid"``) — literówka w przykładzie JSON
  albo w obliczeniach zatrzymuje aplikację, zamiast cicho rozjechać się z frontem;
- modele zapytań dziedziczą zwykły ``BaseModel`` — nadmiarowe query params są ignorowane;
- jednostki są w nazwach pól (``_km``, ``_m``, ``_deg``), czas zawsze UTC.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "0.1.0"
DATA_START = datetime(2000, 1, 1, tzinfo=timezone.utc)
DATA_END = datetime(2100, 1, 1, tzinfo=timezone.utc)
MAX_SERIES_POINTS = 2000


class Contract(BaseModel):
    """Baza wszystkich modeli odpowiedzi: nieznane pola są błędem."""

    model_config = ConfigDict(extra="forbid")


# --- Typy geometryczne -------------------------------------------------------------------


class Vec3(Contract):
    """Wektor 3D. Układ odniesienia i jednostki wynikają z nazwy pola i ``meta.frame``."""

    x: float
    y: float
    z: float


class GeoPoint(Contract):
    """Punkt na sferze (szerokość/długość w stopniach, długość wschodnia dodatnia)."""

    lat_deg: float = Field(ge=-90, le=90)
    lon_deg: float = Field(ge=-180, le=180)


class SelenoPoint(GeoPoint):
    """Punkt selenograficzny (na Księżycu), te same konwencje co ``GeoPoint``."""


class AltAz(Contract):
    """Położenie na niebie obserwatora: wysokość nad horyzontem i azymut od N zgodnie z ruchem wskazówek."""

    alt_deg: float = Field(ge=-90, le=90)
    az_deg: float = Field(ge=0, lt=360)
    distance_km: float = Field(gt=0)


class AssetRef(Contract):
    """Odnośnik do dużego zasobu (tekstura, mapa wysokości) serwowanego jako plik statyczny."""

    url: str
    width: Optional[int] = None
    height: Optional[int] = None
    format: str


# --- Słowniki ----------------------------------------------------------------------------


class ReferenceFrame(str, Enum):
    ECLIPTIC_J2000_GEOCENTRIC = "ECLIPTIC_J2000_GEOCENTRIC"
    EARTH_MOON_ROTATING = "EARTH_MOON_ROTATING"
    MOON_BODY_FIXED = "MOON_BODY_FIXED"
    EARTH_BODY_FIXED = "EARTH_BODY_FIXED"
    TOPOCENTRIC_HORIZON = "TOPOCENTRIC_HORIZON"


class TimeDependency(str, Enum):
    """``static`` — pobierane raz; ``time_dependent`` — zależy od czasu symulacji."""

    STATIC = "static"
    TIME_DEPENDENT = "time_dependent"


class View(str, Enum):
    """Widok frontendu, w którym żyje warstwa modułu."""

    SPACE = "space"
    SURFACE = "surface"


# --- Koperta odpowiedzi ------------------------------------------------------------------


class ResponseMeta(Contract):
    feature: str
    endpoint: str
    contract_version: str
    source: Literal["example", "computed"]
    frame: Optional[ReferenceFrame] = None
    units: Dict[str, str] = Field(default_factory=dict)


class FeatureResponse(Contract):
    """Baza każdej odpowiedzi endpointu modułu."""

    meta: ResponseMeta


# --- Zapytania ---------------------------------------------------------------------------


def _to_utc_in_range(v: datetime) -> datetime:
    """Naive → UTC, offset → UTC, potem sprawdzenie zakresu danych efemeryd."""
    v = v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    if not DATA_START <= v <= DATA_END:
        raise ValueError(
            f"time {v.isoformat()} is outside the data range "
            f"[{DATA_START.isoformat()}, {DATA_END.isoformat()}]"
        )
    return v


class TimeQuery(BaseModel):
    t: datetime = Field(description="Czas symulacji (ISO 8601, UTC; bez strefy = UTC)")

    @field_validator("t")
    @classmethod
    def _t_utc(cls, v: datetime) -> datetime:
        return _to_utc_in_range(v)


class ObserverFields(BaseModel):
    lat_deg: float = Field(0.0, ge=-90, le=90, description="Szerokość selenograficzna obserwatora")
    lon_deg: float = Field(0.0, ge=-180, le=180, description="Długość selenograficzna obserwatora")


class ObserverQuery(TimeQuery, ObserverFields):
    """Czas + obserwator na Księżycu. Tylko z tych pól składa się zapytanie ``/frame``."""


class RangeQuery(BaseModel):
    start: datetime
    end: datetime
    step_hours: int = Field(1, ge=1, le=24)

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _to_utc_in_range(v)

    @property
    def point_count(self) -> int:
        return (self.end - self.start) // timedelta(hours=self.step_hours) + 1

    @model_validator(mode="after")
    def _check_range(self) -> "RangeQuery":
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        if self.point_count > MAX_SERIES_POINTS:
            raise ValueError(f"range gives {self.point_count} points, the maximum is {MAX_SERIES_POINTS}")
        return self


class ObserverRangeQuery(RangeQuery, ObserverFields):
    pass


class FrameQuery(ObserverQuery):
    keys: Optional[str] = Field(
        None, description="Klucze endpointów po przecinku (np. 'lagrange.points,horizon.view'); brak = wszystkie"
    )


# --- Dane dla providerów -----------------------------------------------------------------


class BodyVectors(Contract):
    """Geocentryczne wektory Słońca i Księżyca (ekliptyka J2000, km) w chwili ``t``."""

    t: datetime
    sun_km: Vec3
    moon_km: Vec3


# --- Manifest i klatka -------------------------------------------------------------------


class EndpointInfo(Contract):
    key: str
    name: str
    path: str
    time_dependency: TimeDependency
    frame: bool


class FeatureInfo(Contract):
    id: str
    title: str
    description: str
    view: View
    frontend_module: str
    endpoints: List[EndpointInfo]


class FeatureManifest(Contract):
    contract_version: str
    features: List[FeatureInfo]


class FrameResponse(Contract):
    t: datetime
    observer: SelenoPoint
    payloads: Dict[str, Dict[str, Any]]
    errors: Dict[str, str]
