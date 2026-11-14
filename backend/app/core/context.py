"""Kontekst aplikacji przekazywany do każdej fasady."""

from dataclasses import dataclass
from typing import Optional

from app.core.providers import EphemerisProvider, TerrainProvider
from app.settings import Settings


@dataclass
class AppContext:
    """Ustawienia + wspólne providery. Providery są ``None``, dopóki ktoś ich nie zaimplementuje."""

    settings: Settings
    ephemeris: Optional[EphemerisProvider] = None
    terrain: Optional[TerrainProvider] = None
