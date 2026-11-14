from app.core.contracts import TimeQuery
from app.core.facade import BaseFacade
from app.features.lagrange.contract import LagrangePoints


class LagrangeFacade(BaseFacade):
    feature_id = "lagrange"

    def points(self, q: TimeQuery) -> LagrangePoints:
        """Prawdziwa implementacja: CR3BP dla μ = 0.012150585. Z ``self.ctx.ephemeris`` wziąć wektor
        Księżyca w chwili t i t+1h: oś x = kierunek do Księżyca, z = normalna orbity (r × v), y = z × x.
        L1–L3 z równania kwintycznego na osi x, L4/L5 w wierzchołkach trójkątów równobocznych;
        przeskalować przez chwilową odległość Ziemia–Księżyc i obrócić do ekliptyki.
        """
        return self.from_example("points", LagrangePoints)
