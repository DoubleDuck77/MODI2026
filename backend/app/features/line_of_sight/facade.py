from app.core.contracts import ObserverQuery, ObserverRangeQuery
from app.core.facade import BaseFacade
from app.features.line_of_sight.contract import LineOfSight, VisibilityWindows


class LineOfSightFacade(BaseFacade):
    feature_id = "line_of_sight"

    def point(self, q: ObserverQuery) -> LineOfSight:
        """Prawdziwa implementacja: położenie Ziemi na niebie obserwatora (``self.ctx.ephemeris`` + baza
        lokalna jak w ``horizon``), elewacja horyzontu terenowego w azymucie Ziemi
        (``self.ctx.terrain.horizon_profile``), ``visible_disk_fraction`` z promienia kątowego tarczy Ziemi
        (~0.95°) względem ``clearance_deg``; ``blocked_by`` = najbliższy obiekt z ``moon_geography``
        na linii wzroku, gdy tarcza jest częściowo zasłonięta.
        """
        return self.from_example("point", LineOfSight)

    def windows(self, q: ObserverRangeQuery) -> VisibilityWindows:
        """Prawdziwa implementacja: ``point`` próbkowany co ``q.step_hours`` w ``[q.start, q.end]``,
        sklejony w przedziały z ``earth_visible``; ``visible_fraction`` = suma okien / długość zakresu.
        """
        return self.from_example("windows", VisibilityWindows)
