"""Fabryka aplikacji FastAPI. Uruchamianie: ``uvicorn app.main:app``."""

from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.context import AppContext
from app.core.contracts import CONTRACT_VERSION
from app.core.feature import FeatureModule
from app.core.registry import FeatureRegistry, discover_features
from app.core.routing import API_PREFIX, build_feature_router, build_frame_router, build_manifest_router
from app.settings import Settings

__all__ = ["API_PREFIX", "app", "create_app"]


class RevalidatingStaticFiles(StaticFiles):
    """Pliki frontendu z ``Cache-Control: no-cache``.

    Bez nagłówka przeglądarka cache'uje moduły ES heurystycznie i po zmianie kodu wykonuje
    stary plik. ``no-cache`` wymusza rewalidację (ETag → 304), więc nic nie jest pobierane
    ponownie, gdy plik się nie zmienił.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(settings: Optional[Settings] = None, features: Optional[List[FeatureModule]] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    features = discover_features() if features is None else features
    registry = FeatureRegistry(features, AppContext(settings=settings))

    app = FastAPI(
        title="MODI 2026 API",
        version=CONTRACT_VERSION,
        description="Moduły: efemerydy, Lagrange, geografia i oświetlenie Księżyca, horyzont, "
        "line-of-sight, wygląd Ziemi. Przykłady kontraktów: contracts/examples/.",
    )
    app.state.registry = registry
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "features": len(registry.features())}

    app.include_router(build_manifest_router(registry), prefix=API_PREFIX, tags=["system"])
    app.include_router(build_frame_router(registry), prefix=API_PREFIX, tags=["system"])
    app.include_router(build_feature_router(registry), prefix=API_PREFIX)

    app.mount("/textures", StaticFiles(directory=settings.textures_dir, check_dir=False), name="textures")
    # Frontend jako ostatni mount: łapie wszystko, czego nie obsłużyły trasy powyżej.
    app.mount("/", RevalidatingStaticFiles(directory=settings.frontend_dir, html=True, check_dir=False), name="frontend")
    return app


app = create_app()
