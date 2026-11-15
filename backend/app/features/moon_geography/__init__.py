from app.core.contracts import TimeDependency, View
from app.core.feature import Endpoint, FeatureModule
from app.features.moon_geography.contract import MoonFeatureCatalog, MoonTerrain
from app.features.moon_geography.facade import MoonGeographyFacade

FEATURE = FeatureModule(
    id="moon_geography",
    title="Lunar geography: craters, mountains, maria",
    description="Katalog obiektów powierzchni i opis terenu (tekstury, mapa wysokości).",
    view=View.SPACE,
    facade=MoonGeographyFacade,
    endpoints=(
        Endpoint(name="features", handler="features", response=MoonFeatureCatalog,
                 time_dependency=TimeDependency.STATIC, summary="Katalog kraterów, gór i mórz"),
        Endpoint(name="terrain", handler="terrain", response=MoonTerrain,
                 time_dependency=TimeDependency.STATIC, summary="Tekstury i mapa wysokości terenu"),
    ),
)
