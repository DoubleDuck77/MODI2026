from app.core.contracts import ObserverQuery
from app.core.facade import BaseFacade
from app.features.horizon.contract import HorizonView


class HorizonFacade(BaseFacade):
    feature_id = "horizon"

    def view(self, q: ObserverQuery) -> HorizonView:
        """Prawdziwa implementacja: profil z ``self.ctx.terrain.horizon_profile(observer, az_step_deg=1.0)``
        (krok wybiera backend, front czyta go z payloadu), wysokość obserwatora z ``elevation_m``;
        alt/az Ziemi i Słońca jak ``to_alt_az`` w ``lunar_stellarium.py:104`` (baza north/east/up
        z ``get_topocentric_vectors``), odległości od punktu obserwatora, nie od środka Księżyca.
        """
        return self.from_example("view", HorizonView)
