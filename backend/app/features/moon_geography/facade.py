from app.core.facade import BaseFacade
from app.features.moon_geography.contract import MoonFeatureCatalog, MoonTerrain


class MoonGeographyFacade(BaseFacade):
    feature_id = "moon_geography"

    def features(self) -> MoonFeatureCatalog:
        """Prawdziwa implementacja: katalog z pliku danych (np. IAU Gazetteer of Planetary Nomenclature),
        wczytany raz i trzymany w pamięci. Id obiektów są stabilne — używają ich ``moon_illumination``
        (cienie) i ``line_of_sight`` (``blocked_by``).
        """
        return self.from_example("features", MoonFeatureCatalog)

    def terrain(self) -> MoonTerrain:
        """Prawdziwa implementacja: opis zasobów terenu. Gdy pojawi się mapa wysokości (np. LOLA DEM
        jako 16-bit PNG w ``Textures/``), uzupełnić ``height_map``/``normal_map`` i ``height_range_m``.
        """
        return self.from_example("terrain", MoonTerrain)
