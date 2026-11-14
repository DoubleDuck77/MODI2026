from app.core.contracts import TimeQuery
from app.core.facade import BaseFacade
from app.features.moon_illumination.contract import MoonIllumination


class MoonIlluminationFacade(BaseFacade):
    feature_id = "moon_illumination"

    def state(self, q: TimeQuery) -> MoonIllumination:
        """Prawdziwa implementacja: z ``self.ctx.ephemeris`` wektory Słońca i Ziemi względem Księżyca,
        obrót do układu ciała macierzą jak ``get_lunar_body_matrix`` (``lunar_stellarium.py:56``);
        punkt podsłoneczny/podziemski z kierunków, terminator = okrąg wielki 90° od punktu podsłonecznego;
        dla obiektów z ``moon_geography``: wysokość Słońca w ich środku, cień ≈ głębokość / tan(elewacja).
        Renderer używa ``sun_dir_body`` jako uniformu shadera terenu.
        """
        return self.from_example("state", MoonIllumination)
