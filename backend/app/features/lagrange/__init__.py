from app.core.contracts import TimeQuery, View
from app.core.feature import Endpoint, FeatureModule
from app.features.lagrange.contract import LagrangePoints
from app.features.lagrange.facade import LagrangeFacade

FEATURE = FeatureModule(
    id="lagrange",
    title="Punkty Lagrange'a Ziemia–Księżyc",
    description="Położenia L1–L5 w ekliptyce i w układzie rotującym, ze stabilnością.",
    view=View.SPACE,
    facade=LagrangeFacade,
    endpoints=(
        Endpoint(name="points", handler="points", response=LagrangePoints, params=TimeQuery, frame=True,
                 summary="Punkty L1–L5 w chwili t"),
    ),
)
