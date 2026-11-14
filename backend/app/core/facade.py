"""Klasa bazowa fasad modułów."""

from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Type, TypeVar

from app.core.context import AppContext
from app.core.contracts import FeatureResponse

R = TypeVar("R", bound=FeatureResponse)


class ExampleNotFoundError(FileNotFoundError):
    """Brak pliku ``contracts/examples/<feature>.<endpoint>.json``."""


def example_path(examples_dir: Path, feature_id: str, endpoint: str) -> Path:
    return examples_dir / f"{feature_id}.{endpoint}.json"


@lru_cache(maxsize=None)
def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


class BaseFacade:
    """Fasada modułu: jedna instancja na moduł, bezstanowa, metody synchroniczne.

    Każda metoda publiczna odpowiada jednemu ``Endpoint`` (pole ``handler``) i zwraca model
    odpowiedzi. Dopóki moduł nie ma implementacji, metoda zwraca ``self.from_example(...)``.
    """

    feature_id: ClassVar[str] = ""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def from_example(self, endpoint: str, model: Type[R]) -> R:
        """Zwraca przykład kontraktu z ``contracts/examples`` zwalidowany jako ``model``."""
        path = example_path(self.ctx.settings.examples_dir, self.feature_id, endpoint)
        try:
            raw = _read_bytes(path)
        except FileNotFoundError:
            raise ExampleNotFoundError(f"Brak przykładu kontraktu: {path}") from None
        return model.model_validate_json(raw)
