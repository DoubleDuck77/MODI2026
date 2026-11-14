"""Kontrakt modułu ``moon_geography``: katalog kraterów, gór i mórz oraz opis terenu (tekstury, mapa wysokości)."""

from typing import List, Literal, Optional, Tuple

from pydantic import Field, model_validator

from app.core.contracts import AssetRef, Contract, FeatureResponse, SelenoPoint

MoonFeatureKind = Literal["crater", "mountain", "mare"]


class MoonFeature(Contract):
    id: str = Field(pattern=r"^[a-z0-9_]+$", description="Stabilny identyfikator, używany przez inne moduły")
    name: str
    kind: MoonFeatureKind
    center: SelenoPoint
    diameter_km: float = Field(gt=0)
    depth_km: Optional[float] = Field(None, description="Wymagane dla kraterów")
    height_m: Optional[float] = Field(None, description="Wymagane dla gór")

    @model_validator(mode="after")
    def _kind_fields(self) -> "MoonFeature":
        if self.kind == "crater" and self.depth_km is None:
            raise ValueError(f"krater '{self.id}' wymaga depth_km")
        if self.kind == "mountain" and self.height_m is None:
            raise ValueError(f"góra '{self.id}' wymaga height_m")
        return self


class MoonFeatureCatalog(FeatureResponse):
    features: List[MoonFeature]

    @model_validator(mode="after")
    def _unique_ids(self) -> "MoonFeatureCatalog":
        ids = [f.id for f in self.features]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"zduplikowane id obiektów: {dupes}")
        return self


class MoonTerrain(FeatureResponse):
    """Opis terenu dla renderera. Duże dane idą jako pliki statyczne (``AssetRef``), nie w JSON-ie."""

    radius_km: float = Field(gt=0)
    projection: Literal["equirectangular"]
    lon_origin_deg: float = Field(-180.0, description="Długość odpowiadająca u=0 tekstury")
    color_map: AssetRef
    color_map_preview: AssetRef = Field(description="Mała tekstura do szybkiego pierwszego renderu")
    height_map: Optional[AssetRef] = None
    normal_map: Optional[AssetRef] = None
    height_range_m: Tuple[float, float] = Field(description="Piksel 0..255 mapy wysokości → min..max [m]")
