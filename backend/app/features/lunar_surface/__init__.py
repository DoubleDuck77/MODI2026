from app.core.contracts import TimeDependency, View
from app.core.feature import Endpoint, FeatureModule
from app.features.lunar_surface.contract import (
    LunarSky,
    ObserverGeometry,
    ObserverGeometryQuery,
    StarField,
    SurfaceCatalog,
    SurfaceQuery,
)
from app.features.lunar_surface.facade import LunarSurfaceFacade, tile_routes

FEATURE = FeatureModule(
    id="lunar_surface",
    title="Widok z powierzchni Księżyca (geografia)",
    description="Geometria obserwatora, niebo (Ziemia, Słońce, zaćmienia) i kafle DEM/albedo LOLA, liczone przez geografia.py; teren rysuje WebGL2 w przeglądarce. Wizualizacja: /sim.html#surface.",
    view=View.SURFACE,
    facade=LunarSurfaceFacade,
    endpoints=(
        Endpoint(name="catalog", handler="catalog", response=SurfaceCatalog,
                 time_dependency=TimeDependency.STATIC,
                 summary="Stałe LOD terenu i opis kafli DEM/albedo"),
        Endpoint(name="observer", handler="observer", response=ObserverGeometry, params=ObserverGeometryQuery,
                 summary="Grunt, nachylenie i profil horyzontu obserwatora (721 azymutów)"),
        Endpoint(name="sky", handler="sky", response=LunarSky, params=SurfaceQuery,
                 summary="Ziemia i Słońce na niebie obserwatora w chwili t"),
        Endpoint(name="stars", handler="stars", response=StarField,
                 time_dependency=TimeDependency.STATIC,
                 summary="Gwiazdy tła geografii (1200, seed 42) w ekliptyce J2000"),
    ),
    extra_routes=tile_routes,
)
