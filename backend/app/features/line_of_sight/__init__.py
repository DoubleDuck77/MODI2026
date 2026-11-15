from app.core.contracts import ObserverQuery, ObserverRangeQuery, View
from app.core.feature import Endpoint, FeatureModule
from app.features.line_of_sight.contract import LineOfSight, VisibilityWindows
from app.features.line_of_sight.facade import LineOfSightFacade

FEATURE = FeatureModule(
    id="line_of_sight",
    title="Line of sight to Earth",
    description="Widoczność Ziemi z punktu na Księżycu z uwzględnieniem terenu i okna widoczności w czasie.",
    view=View.SURFACE,
    facade=LineOfSightFacade,
    endpoints=(
        Endpoint(name="point", handler="point", response=LineOfSight, params=ObserverQuery, frame=True,
                 summary="Czy obserwator widzi Ziemię w chwili t"),
        Endpoint(name="windows", handler="windows", response=VisibilityWindows, params=ObserverRangeQuery,
                 summary="Okna widoczności Ziemi w zakresie czasu"),
    ),
)
