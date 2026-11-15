from app.core.contracts import RangeQuery, TimeQuery, View
from app.core.feature import Endpoint, FeatureModule
from app.features.ephemeris.contract import EphemerisSeries, EphemerisState
from app.features.ephemeris.facade import EphemerisFacade

FEATURE = FeatureModule(
    id="ephemeris",
    title="Ephemerides: Earth–Moon–Sun geometry",
    description="Geocentryczne położenia Słońca i Księżyca, odległości, faza Księżyca i Ziemi.",
    view=View.SPACE,
    facade=EphemerisFacade,
    endpoints=(
        Endpoint(name="state", handler="state", response=EphemerisState, params=TimeQuery, frame=True,
                 summary="Stan układu w chwili t"),
        Endpoint(name="series", handler="series", response=EphemerisSeries, params=RangeQuery,
                 summary="Szereg czasowy do interpolacji po stronie klienta"),
    ),
)
