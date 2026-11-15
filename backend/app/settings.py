"""Ustawienia ścieżek. W Dockerze z env ``MODI_*``, lokalnie względem roota repo."""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    contracts_dir: Path
    frontend_dir: Path
    textures_dir: Path
    coords_dir: Path
    scripts_dir: Path  # katalog z root-skryptami (neworb.py, geografia.py, radius.py, generator.py)
    pds_data_dir: Path  # mapy zasobów PDS (lunar_pds_data)
    topo_cache_dir: Path  # zapisywalny cache horyzontu LOLA dla /api/wykresy (w Dockerze /tmp)

    @property
    def examples_dir(self) -> Path:
        return self.contracts_dir / "examples"

    @classmethod
    def from_env(cls) -> "Settings":
        def path(var: str, default: str) -> Path:
            return Path(os.environ.get(var, REPO_ROOT / default))

        return cls(
            contracts_dir=path("MODI_CONTRACTS_DIR", "contracts"),
            frontend_dir=path("MODI_FRONTEND_DIR", "frontend"),
            textures_dir=path("MODI_TEXTURES_DIR", "Textures"),
            coords_dir=path("MODI_COORDS_DIR", "coords"),
            scripts_dir=path("MODI_SCRIPTS_DIR", "."),
            pds_data_dir=path("MODI_PDS_DATA_DIR", "lunar_pds_data"),
            topo_cache_dir=path("MODI_TOPO_CACHE_DIR", "moon_topo_cache"),
        )
