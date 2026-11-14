from app.core.contracts import ObserverQuery, View
from app.core.feature import Endpoint, FeatureModule
from app.features.horizon.contract import HorizonView
from app.features.horizon.facade import HorizonFacade

FEATURE = FeatureModule(
    id="horizon",
    title="Horyzont obserwatora na Księżycu",
    description="Profil horyzontu terenowego oraz Ziemia i Słońce na niebie obserwatora.",
    view=View.SURFACE,
    facade=HorizonFacade,
    endpoints=(
        Endpoint(name="view", handler="view", response=HorizonView, params=ObserverQuery, frame=True,
                 summary="Widok horyzontu dla obserwatora w chwili t"),
    ),
)
