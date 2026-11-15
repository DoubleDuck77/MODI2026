from app.core.contracts import TimeDependency, View
from app.core.feature import Endpoint, FeatureModule
from app.features.lunar_resources.contract import ResourceCatalog, ResourceRoi, RoiQuery
from app.features.lunar_resources.facade import LunarResourcesFacade, layer_routes

FEATURE = FeatureModule(
    id="lunar_resources",
    title="Lunar geochemical resources (radius)",
    description="Średnie ważone polem, min/max i różnica względem średniej globalnej 10 zasobów LP-GRS w promieniu R od punktu, liczone przez radius.py i generator.py. Wizualizacja: /sim.html#resources.",
    view=View.SURFACE,
    facade=LunarResourcesFacade,
    endpoints=(
        Endpoint(name="catalog", handler="catalog", response=ResourceCatalog,
                 time_dependency=TimeDependency.STATIC,
                 summary="Warstwy, mapy kolorów, grupy wykresów, suwaki i wartości domyślne"),
        Endpoint(name="roi", handler="roi", response=ResourceRoi, params=RoiQuery,
                 summary="Statystyki zasobów w promieniu R i kontur promienia na mapie"),
    ),
    extra_routes=layer_routes,
)
