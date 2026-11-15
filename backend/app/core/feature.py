"""Deskryptory modułu i endpointu. Każdy moduł wystawia ``FEATURE = FeatureModule(...)``."""

from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Type

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.contracts import FeatureResponse, TimeDependency, View
from app.core.facade import BaseFacade


@dataclass(frozen=True)
class Endpoint:
    """Jeden endpoint ``GET /api/v1/{feature_id}/{name}``.

    - ``handler``: nazwa metody fasady,
    - ``params``: model zapytania (``None`` dla endpointów ``STATIC``),
    - ``frame``: czy endpoint wchodzi do zbiorczego ``/api/v1/frame``
      (wymaga ``TIME_DEPENDENT`` i parametrów będących podzbiorem ``ObserverQuery``).
    """

    name: str
    handler: str
    response: Type[FeatureResponse]
    params: Optional[Type[BaseModel]] = None
    time_dependency: TimeDependency = TimeDependency.TIME_DEPENDENT
    frame: bool = False
    summary: str = ""


@dataclass(frozen=True)
class FeatureModule:
    """Deskryptor modułu.

    ``extra_routes`` służy wyłącznie do danych binarnych (kafle, obrazy): router dostaje
    fasadę modułu i jest montowany pod ``/api/v1/{id}/…``. Tych tras nie ma w manifeście
    ani w ``/frame`` i nie mają przykładów kontraktu; dane JSON idą zwykłymi ``endpoints``.
    """

    id: str
    title: str
    description: str
    view: View
    facade: Type[BaseFacade]
    endpoints: Tuple[Endpoint, ...]
    extra_routes: Optional[Callable[[BaseFacade], APIRouter]] = None

    def key(self, ep: Endpoint) -> str:
        return f"{self.id}.{ep.name}"

    def path(self, ep: Endpoint) -> str:
        return f"/{self.id}/{ep.name}"

    @property
    def frontend_module(self) -> str:
        return f"/js/features/{self.id}/layer.js"
