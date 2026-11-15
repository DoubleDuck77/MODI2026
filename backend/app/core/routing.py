"""Generowanie tras z deskryptorów modułów + manifest + zbiorczy ``/frame``.

UWAGA: ten plik NIE może mieć ``from __future__ import annotations`` — FastAPI czyta adnotacje
funkcji budowanych dynamicznie w ``_make_route`` i potrzebuje prawdziwych obiektów typów.
"""

import logging
from typing import Annotated, Dict, List

from fastapi import APIRouter, HTTPException, Query, Response

from app.core.contracts import (
    CONTRACT_VERSION,
    EndpointInfo,
    FeatureInfo,
    FeatureManifest,
    FrameQuery,
    FrameResponse,
    SelenoPoint,
    TimeDependency,
)
from app.core.feature import Endpoint
from app.core.registry import FeatureRegistry

API_PREFIX = "/api/v1"
STATIC_CACHE = "public, max-age=300"
NO_STORE = "no-store"

logger = logging.getLogger(__name__)


def _make_route(registry: FeatureRegistry, key: str, ep: Endpoint):
    cache = STATIC_CACHE if ep.time_dependency is TimeDependency.STATIC else NO_STORE
    if ep.params is None:

        def route(response: Response):
            response.headers["Cache-Control"] = cache
            return registry.call(key, None)

    else:

        def route(response: Response, params: Annotated[ep.params, Query()]):
            response.headers["Cache-Control"] = cache
            return registry.call(key, params)

    return route


def build_feature_router(registry: FeatureRegistry) -> APIRouter:
    router = APIRouter()
    for feature in registry.features():
        for ep in feature.endpoints:
            key = feature.key(ep)
            router.add_api_route(
                feature.path(ep),
                _make_route(registry, key, ep),
                methods=["GET"],
                response_model=ep.response,
                name=key,
                summary=ep.summary or key,
                tags=[feature.id],
            )
        if feature.extra_routes is not None:
            # Trasy binarne: poza manifestem i /frame, bez przykładów kontraktu.
            router.include_router(
                feature.extra_routes(registry.facade(feature.id)),
                prefix=f"/{feature.id}",
                tags=[feature.id],
            )
    return router


def build_manifest_router(registry: FeatureRegistry) -> APIRouter:
    manifest = FeatureManifest(
        contract_version=CONTRACT_VERSION,
        features=[
            FeatureInfo(
                id=f.id,
                title=f.title,
                description=f.description,
                view=f.view,
                frontend_module=f.frontend_module,
                endpoints=[
                    EndpointInfo(
                        key=f.key(ep),
                        name=ep.name,
                        path=API_PREFIX + f.path(ep),
                        time_dependency=ep.time_dependency,
                        frame=ep.frame,
                    )
                    for ep in f.endpoints
                ],
            )
            for f in registry.features()
        ],
    )
    router = APIRouter()

    @router.get("/features", response_model=FeatureManifest, summary="Manifest modułów dla frontendu")
    def features() -> FeatureManifest:
        return manifest

    return router


def build_frame_router(registry: FeatureRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/frame", response_model=FrameResponse, summary="Wszystkie dane zależne od czasu w jednym zapytaniu")
    def frame(response: Response, query: Annotated[FrameQuery, Query()]) -> FrameResponse:
        valid = registry.frame_keys()
        if query.keys is None:
            keys = valid
        else:
            keys = [k.strip() for k in query.keys.split(",") if k.strip()]
            invalid = [k for k in keys if k not in valid]
            if invalid:
                raise HTTPException(status_code=422, detail={"invalid_keys": invalid, "valid_keys": valid})

        base = query.model_dump()
        payloads: Dict[str, dict] = {}
        errors: Dict[str, str] = {}
        for key in keys:
            _, ep = registry.endpoint(key)
            try:
                params = ep.params.model_validate({name: base[name] for name in ep.params.model_fields})
                payloads[key] = registry.call(key, params).model_dump(mode="json")
            except Exception as e:  # jedna padająca fasada nie może zabić całej klatki
                logger.exception("frame: endpoint %s zgłosił wyjątek", key)
                errors[key] = f"{type(e).__name__}: {e}"

        response.headers["Cache-Control"] = NO_STORE
        return FrameResponse(
            t=query.t,
            observer=SelenoPoint(lat_deg=query.lat_deg, lon_deg=query.lon_deg),
            payloads=payloads,
            errors=errors,
        )

    return router


__all__: List[str] = [
    "API_PREFIX",
    "build_feature_router",
    "build_manifest_router",
    "build_frame_router",
]
