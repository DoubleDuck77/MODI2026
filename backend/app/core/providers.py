"""Interfejsy providerów danych domenowych (bez implementacji).

Providery to wspólne źródła danych, z których korzystają fasady wielu modułów
(np. ``line_of_sight`` potrzebuje efemeryd i terenu). Fasady sięgają po nie przez
``self.ctx``, nigdy przez HTTP do innych modułów.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List

from app.core.contracts import BodyVectors, SelenoPoint


class EphemerisProvider(ABC):
    """Położenia Słońca i Księżyca, geocentrycznie, ekliptyka J2000, w km.

    Uwaga dla implementacji opartej o ``coords/*.csv``: wartości w CSV są w METRACH
    (|moon| ≈ 3.61e8), trzeba je podzielić przez 1000. Dane są co godzinę od
    2000-01-01 00:00 do 2100-01-01 00:00; między godzinami interpolacja liniowa.
    """

    @abstractmethod
    def state_at(self, t: datetime) -> BodyVectors:
        """Wektory w chwili ``t`` (UTC)."""

    @abstractmethod
    def series(self, start: datetime, end: datetime, step: timedelta) -> List[BodyVectors]:
        """Wektory od ``start`` do ``end`` włącznie co ``step``."""


class TerrainProvider(ABC):
    """Rzeźba terenu Księżyca (np. z mapy wysokości LOLA)."""

    @abstractmethod
    def elevation_m(self, p: SelenoPoint) -> float:
        """Wysokość terenu względem promienia odniesienia 1737.4 km, w metrach."""

    @abstractmethod
    def horizon_profile(self, observer: SelenoPoint, az_step_deg: float) -> List[float]:
        """Elewacja horyzontu terenowego [deg] dla azymutów 0, step, 2·step, … < 360 (N=0, E=90)."""
