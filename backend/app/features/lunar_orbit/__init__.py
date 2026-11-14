from app.core.contracts import TimeDependency, View
from app.core.feature import Endpoint, FeatureModule
from app.features.lunar_orbit.contract import (
    OrbitCatalog,
    OrbitInitialQuery,
    OrbitPropagateQuery,
    OrbitState,
    OrbitTrack,
)
from app.features.lunar_orbit.facade import LunarOrbitFacade

FEATURE = FeatureModule(
    id="lunar_orbit",
    title="Symulator orbit wokół Księżyca (neworb)",
    description="RK4 + J2/C22/J3/J4 + 14 masconów + Ziemia i Słońce, liczone przez neworb.py. Wizualizacja: /sim.html#orbit.",
    view=View.SPACE,
    facade=LunarOrbitFacade,
    endpoints=(
        Endpoint(name="catalog", handler="catalog", response=OrbitCatalog,
                 time_dependency=TimeDependency.STATIC,
                 summary="Stałe, presety, mascony i punkty orientacyjne"),
        Endpoint(name="initial", handler="initial", response=OrbitState, params=OrbitInitialQuery,
                 summary="Stan początkowy presetu (lub własnej orbity) w chwili t"),
        Endpoint(name="propagate", handler="propagate", response=OrbitTrack, params=OrbitPropagateQuery,
                 summary="Propagacja stanu przez duration_s z próbkami co sample_dt_s"),
    ),
)
