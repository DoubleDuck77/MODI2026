from app.core.contracts import TimeQuery
from app.core.facade import BaseFacade
from app.features.earth_appearance.contract import EarthAppearance


class EarthAppearanceFacade(BaseFacade):
    feature_id = "earth_appearance"

    def state(self, q: TimeQuery) -> EarthAppearance:
        """Prawdziwa implementacja: ``rotation.angle_deg`` z GMST(t) (280.46061837 + 360.98564736629·d od J2000);
        chmury: ``angle_deg = (angle0 + rate·h) mod 360`` z własnym ``rate_deg_per_hour`` (inny niż planeta);
        punkt podsłoneczny z deklinacji Słońca i równania czasu (wektor Słońca z ``self.ctx.ephemeris``);
        dla każdego miasta elewacja Słońca i ``lights_on = elewacja <= on_below_sun_elevation_deg``.
        """
        return self.from_example("state", EarthAppearance)
