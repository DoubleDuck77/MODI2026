import os
from pathlib import Path
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
    """Pliki frontendu z ``Cache-Control: no-cache`` oraz obsługą katalogów nadrzędnych."""

    def __init__(self, *args, extra_dirs: Optional[List[Path]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        existing = {os.path.realpath(str(d)) for d in self.all_directories}
        for extra in extra_dirs or []:
            resolved = os.path.realpath(str(extra))
            if resolved not in existing:
                self.all_directories.append(resolved)
                existing.add(resolved)

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

    parent_dir = Path(settings.frontend_dir).resolve().parent
    # Frontend jako ostatni mount: szuka najpierw w frontend/, a potem w katalogu ponad frontend/.
    app.mount(
        "/",
        RevalidatingStaticFiles(
            directory=settings.frontend_dir,
            extra_dirs=[parent_dir],
            html=True,
            check_dir=False,
        ),
        name="frontend",
    )
    return app


app = create_app()