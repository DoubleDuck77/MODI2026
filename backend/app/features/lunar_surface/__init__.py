from app.core.contracts import View
from app.core.feature import Endpoint, FeatureModule
from app.features.lunar_surface.contract import LunarSky, LunarTerrainPatch, SurfaceQuery, TerrainQuery
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
        Endpoint(name="terrain", handler="terrain", response=LunarTerrainPatch, params=TerrainQuery,
                 summary="Siatka biegunowa terenu (720 az × 480 promieni) i profil horyzontu"),
    ),
)
