from app.core.contracts import RangeQuery, TimeQuery
from app.core.facade import BaseFacade
from app.features.ephemeris.contract import EphemerisSeries, EphemerisState


class EphemerisFacade(BaseFacade):
    feature_id = "ephemeris"

    def state(self, q: TimeQuery) -> EphemerisState:
        """Prawdziwa implementacja: ``self.ctx.ephemeris.state_at(q.t)`` (interpolacja liniowa między
        godzinami jak ``get_topocentric_vectors`` w ``lunar_stellarium.py:63``), z tego odległości,
        elongacja Słońce–Ziemia–Księżyc, kąt fazowy Słońce–Księżyc–Ziemia,
        ``illuminated_fraction = (1 + cos(phase_angle)) / 2``, ``waxing`` z kierunku zmiany elongacji.
        """
        return self.from_example("state", EphemerisState)

    def series(self, q: RangeQuery) -> EphemerisSeries:
        """Prawdziwa implementacja: ``self.ctx.ephemeris.series(q.start, q.end, timedelta(hours=q.step_hours))``
        spakowane kolumnowo — frontend interpoluje między punktami zamiast pytać co klatkę.
        """
        return self.from_example("series", EphemerisSeries)
