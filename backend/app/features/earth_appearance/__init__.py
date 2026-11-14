from app.core.contracts import TimeQuery, View
from app.core.feature import Endpoint, FeatureModule
from app.features.earth_appearance.contract import EarthAppearance
from app.features.earth_appearance.facade import EarthAppearanceFacade

FEATURE = FeatureModule(
    id="earth_appearance",
    title="Wygląd Ziemi: rotacja, chmury, światła miast",
    description="Obrót Ziemi, warstwa chmur z własną prędkością, terminator i światła miast po stronie nocnej.",
    view=View.SPACE,
    facade=EarthAppearanceFacade,
    endpoints=(
        Endpoint(name="state", handler="state", response=EarthAppearance, params=TimeQuery, frame=True,
                 summary="Wygląd Ziemi w chwili t"),
    ),
)
