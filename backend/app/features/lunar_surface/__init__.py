from app.core.contracts import TimeDependency, View
from app.core.feature import Endpoint, FeatureModule
from app.features.lunar_surface.contract import LunarSky, LunarTerrainPatch, StarField, SurfaceQuery, TerrainQuery
from app.features.lunar_surface.facade import LunarSurfaceFacade

FEATURE = FeatureModule(
    id="lunar_surface",
    title="Widok z powierzchni Księżyca (newlunar)",
    description="Niebo (Ziemia, Słońce, zaćmienia) i teren LOLA wokół obserwatora, liczone przez newlunar.py. Wizualizacja: /sim.html#surface.",
    view=View.SURFACE,
    facade=LunarSurfaceFacade,
    endpoints=(
        Endpoint(name="sky", handler="sky", response=LunarSky, params=SurfaceQuery,
                 summary="Ziemia i Słońce na niebie obserwatora w chwili t"),
        Endpoint(name="stars", handler="stars", response=StarField,
                 time_dependency=TimeDependency.STATIC,
                 summary="Gwiazdy tła newlunar (1200, seed 42) w ekliptyce J2000"),
        Endpoint(name="terrain", handler="terrain", response=LunarTerrainPatch, params=TerrainQuery,
                 summary="Siatka biegunowa terenu (720 az × 480 promieni) i profil horyzontu"),
    ),
)
