from app.core.contracts import TimeQuery, View
from app.core.feature import Endpoint, FeatureModule
from app.features.lagrange.contract import LagrangePoints
from app.features.lagrange.facade import LagrangeFacade

FEATURE = FeatureModule(
    id="lagrange",
    title="Earth–Moon Lagrange points",
    description="Położenia L1–L5 w ekliptyce i w układzie rotującym, ze stabilnością.",
    view=View.SPACE,
    facade=LagrangeFacade,
    endpoints=(
        Endpoint(name="points", handler="points", response=LagrangePoints, params=TimeQuery, frame=True,
                 summary="Punkty L1–L5 w chwili t"),
    ),
)
