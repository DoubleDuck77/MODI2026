from app.core.contracts import TimeQuery, View
from app.core.feature import Endpoint, FeatureModule
from app.features.moon_illumination.contract import MoonIllumination
from app.features.moon_illumination.facade import MoonIlluminationFacade

FEATURE = FeatureModule(
    id="moon_illumination",
    title="Oświetlenie i cienie Księżyca",
    description="Kierunek Słońca w układzie Księżyca, terminator, libracja i cienie obiektów.",
    view=View.SPACE,
    facade=MoonIlluminationFacade,
    endpoints=(
        Endpoint(name="state", handler="state", response=MoonIllumination, params=TimeQuery, frame=True,
                 summary="Oświetlenie w chwili t"),
    ),
)
