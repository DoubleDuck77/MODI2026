#!/usr/bin/env python3
"""
Generator equirectangularnych map złóż księżycowych dopasowanych do moon_color.jpg.
Pobiera i przetwarza wyłącznie 10 czystych zasobów geochemicznych z NASA PDS
Geosciences Node (Lunar Prospector Gamma-Ray Spectrometer LP-GRS).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

import matplotlib.pyplot as plt
import numpy as np
import requests
from PIL import Image
from scipy.interpolate import griddata
from scipy.ndimage import distance_transform_edt, zoom

# --- KONFIGURACJA ---
BASE_IMAGE_PATH = Path("moon_color.jpg")   # Podkład 2:1 (1024x512 px)
DATA_CACHE_DIR = Path("lunar_pds_data")    # Katalog z pobranymi plikami NASA PDS / GeoTIFF
OUTPUT_DIR = Path("lunar_resource_maps")   # Katalog wyjściowy na mapy PNG

PDS_INDEX_URL = "https://pds-geosciences.wustl.edu/missions/lunarp/reduced_special.html"
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (LunarResourceMapper/4.0; scientific-use)"}

# Przeliczniki stechiometryczne (pierwiastek -> tlenek)
F_SI_TO_SIO2  = 60.0843 / 28.0855          # Si -> SiO2  (2.139335)
F_TI_TO_TIO2  = 79.8658 / 47.8670          # Ti -> TiO2  (1.668494)
F_FE_TO_FEO   = 71.8444 / 55.8450          # Fe -> FeO   (1.286497)
F_AL_TO_AL2O3 = 101.9613 / (2 * 26.98154)  # Al -> Al2O3 (1.889464)
F_MG_TO_MGO   = 40.3044 / 24.3050          # Mg -> MgO   (1.658276)
F_CA_TO_CAO   = 56.0774 / 40.0780          # Ca -> CaO   (1.399207)
F_K_TO_K2O    = 94.1960 / (2 * 39.0983)    # K  -> K2O   (1.204605)

# Wyłącznie 10 surowców geochemicznych LP-GRS (zero neutronów i zero wodoru)
PDS_FILE_CATALOG: dict[str, tuple[str, float, str]] = {
    "silicon5d.txt":   ("SiO2",   F_SI_TO_SIO2,     "NASA PDS LP-GRS 5° (silicon5d.txt, Si -> SiO₂)"),
    "oxygen5d.txt":    ("O",      1.0,              "NASA PDS LP-GRS 5° (oxygen5d.txt)"),
    "titanium2d.txt":  ("TiO2",   F_TI_TO_TIO2,     "NASA PDS LP-GRS 2° (titanium2d.txt, Ti -> TiO₂)"),
    "titanium5d.txt":  ("TiO2",   F_TI_TO_TIO2,     "NASA PDS LP-GRS 5° (titanium5d.txt, Ti -> TiO₂)"),
    "ironhd.txt":      ("FeO",    1.0,              "NASA PDS LP-GRS 0.5° (ironhd.txt, Lawrence et al. 2002)"),
    "iron5d.txt":      ("FeO",    F_FE_TO_FEO,      "NASA PDS LP-GRS 5° (iron5d.txt, Fe -> FeO)"),
    "aluminum5d.txt":  ("Al2O3",  F_AL_TO_AL2O3,    "NASA PDS LP-GRS 5° (aluminum5d.txt, Al -> Al₂O₃)"),
    "magnesium5d.txt": ("MgO",    F_MG_TO_MGO,      "NASA PDS LP-GRS 5° (magnesium5d.txt, Mg -> MgO)"),
    "calcium5d.txt":   ("CaO",    F_CA_TO_CAO,      "NASA PDS LP-GRS 5° (calcium5d.txt, Ca -> CaO)"),
    "thoriumhd.txt":   ("Th",     1.0,              "NASA PDS LP-GRS 0.5° (thoriumhd.txt, Lawrence et al. 2002)"),
    "thorium5d.txt":   ("Th",     1.0,              "NASA PDS LP-GRS 5° (thorium5d.txt, Prettyman et al. 2002)"),
    "uranium5d.txt":   ("U",      1.0,              "NASA PDS LP-GRS 5° (uranium5d.txt, Prettyman et al. 2002)"),
    "potassium2d.txt": ("K2O",    F_K_TO_K2O / 1e4, "NASA PDS LP-GRS 2° (potassium2d.txt, K ppm -> K₂O %)"),
    "potassium5d.txt": ("K2O",    F_K_TO_K2O / 1e4, "NASA PDS LP-GRS 5° (potassium5d.txt, K ppm -> K₂O %)"),
}

# Definicje 10 map wyjściowych
RESOURCE_SPECS = [
    ("SiO2",  "Krzemionka (SiO₂)",                     "% wag.", "YlOrRd"),
    ("O",     "Tlen związany w regolicie (O)",         "% wag.", "YlGn"),
    ("TiO2",  "Dwutlenek tytanu / Ilmenit (TiO₂)",     "% wag.", "magma"),
    ("FeO",   "Tlenek żelaza (FeO)",                   "% wag.", "inferno"),
    ("Th",    "Tor – znacznik KREEP (Th)",             "ppm",    "viridis"),
    ("U",     "Uran – znacznik KREEP (U)",              "ppm",    "plasma"),
    ("K2O",   "Tlenek potasu – KREEP (K₂O)",           "% wag.", "cividis"),
    ("Al2O3", "Tlenek glinu / Anortozyt (Al₂O₃)",      "% wag.", "GnBu"),
    ("MgO",   "Tlenek magnezu (MgO)",                  "% wag.", "YlGnBu"),
    ("CaO",   "Tlenek wapnia (CaO)",                   "% wag.", "PuBuGn"),
]


def load_base_albedo(image_path: Path) -> tuple[np.ndarray, int, int]:
    """Wczytuje moon_color.jpg i zwraca znormalizowaną jasność albedo."""
    if not image_path.exists():
        raise FileNotFoundError(
            f"Nie znaleziono pliku podkładu '{image_path}'. "
            "Umieść obraz moon_color.jpg w katalogu roboczym."
        )
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    rgb = np.asarray(img, dtype=np.float32) / 255.0
    gray = rgb.mean(axis=2)
    p2, p98 = np.percentile(gray, [2, 98])
    gray_norm = np.clip((gray - p2) / (p98 - p2 + 1e-6), 0.0, 1.0)
    return gray_norm, w, h


def discover_and_download_pds_files(cache_dir: Path) -> list[Path]:
    """Pobiera z NASA PDS wyłącznie 14 plików geochemicznych z PDS_FILE_CATALOG."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    needed_names = set(PDS_FILE_CATALOG.keys())

    missing = [name for name in sorted(needed_names) if not (cache_dir / name).exists()]
    if not missing:
        print(f"[PDS] Wszystkie wymagane pliki ({len(needed_names)}) są już w '{cache_dir}/'.")
        return [cache_dir / name for name in sorted(needed_names)]

    print(f"[PDS] Łączenie z repozytorium: {PDS_INDEX_URL}")
    resp = requests.get(PDS_INDEX_URL, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()

    hrefs = re.findall(r'href=["\']([^"\']+\.txt)["\']', resp.text, flags=re.I)
    url_by_name = {h.split("/")[-1].lower(): urljoin(PDS_INDEX_URL, h) for h in hrefs}

    downloaded: list[Path] = []
    for fname in sorted(needed_names):
        dest = cache_dir / fname
        if dest.exists():
            downloaded.append(dest)
            continue
        url = url_by_name.get(fname)
        if url:
            print(f"  -> Pobieranie: {fname}")
            r = requests.get(url, headers=HTTP_HEADERS, timeout=60)
            if r.status_code == 200:
                dest.write_bytes(r.content)
                downloaded.append(dest)
    return downloaded


def fill_nan_nearest(grid: np.ndarray) -> np.ndarray:
    """Uzupełnia brakujące komórki (NaN) najbliższą poprawną wartością."""
    mask = ~np.isfinite(grid)
    if not np.any(mask):
        return grid
    if np.all(mask):
        return np.zeros_like(grid)
    _, nearest_idx = distance_transform_edt(mask, return_distances=True, return_indices=True)
    return grid[tuple(nearest_idx)]


def rasterize_points_to_equirectangular(
    lat: np.ndarray, lon: np.ndarray, values: np.ndarray, width: int, height: int
) -> np.ndarray:
    """Rzutuje środki pikseli equal-area (lat, lon, value) na siatkę equirectangular (-180..+180, +90..-90)."""
    valid = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(values)
    lat, lon, values = lat[valid], lon[valid], values[valid]
    lon = ((lon + 180.0) % 360.0) - 180.0

    lon_ext = np.concatenate([lon - 360.0, lon, lon + 360.0])
    lat_ext = np.concatenate([lat, lat, lat])
    val_ext = np.concatenate([values, values, values])

    grid_lon = np.linspace(-180.0, 180.0, width, endpoint=False) + (180.0 / width)
    grid_lat = np.linspace(90.0, -90.0, height, endpoint=False) - (90.0 / height)
    mesh_lon, mesh_lat = np.meshgrid(grid_lon, grid_lat)

    pts = np.column_stack((lon_ext, lat_ext))
    g_lin = griddata(pts, val_ext, (mesh_lon, mesh_lat), method="linear")
    g_near = griddata(pts, val_ext, (mesh_lon, mesh_lat), method="nearest")
    return np.where(np.isfinite(g_lin), g_lin, g_near)


def select_measurement_column(mat: np.ndarray, header_lines: list[str]) -> np.ndarray:
    """Wybiera właściwą kolumnę pomiarową z tabeli NASA PDS (pomija binarne maski {0, 1})."""
    n_cols = mat.shape[1]
    candidate_indices = list(range(4, n_cols))
    if not candidate_indices:
        return mat[:, -1]

    if header_lines:
        for hdr in reversed(header_lines):
            tokens = [t.strip().lower() for t in re.split(r"[,;\t]+", hdr) if t.strip()]
            if len(tokens) == n_cols:
                skip_words = ("lat", "lon", "err", "std", "unc", "sigma", "flag", "mask", "id", "num", "count", "pixel", "reg", "mare")
                for idx in candidate_indices:
                    if not any(sw in tokens[idx] for sw in skip_words):
                        col = mat[:, idx]
                        finite = col[np.isfinite(col)]
                        if finite.size > 0 and not set(np.unique(finite)).issubset({0.0, 1.0}):
                            return col

    for idx in candidate_indices:
        col = mat[:, idx].copy()
        col[(np.abs(col) > 1e10) | (col <= -900.0) | (col >= 9990.0)] = np.nan
        finite = col[np.isfinite(col)]
        if finite.size == 0:
            continue
        if set(np.unique(finite)).issubset({0.0, 1.0}):
            continue
        if idx < n_cols - 1 and np.all(np.isclose(finite, np.round(finite))) and np.nanmax(finite) > 20:
            continue
        return col

    return mat[:, 4]


def parse_nasa_pds_txt_file(
    txt_path: Path, scale_factor: float, width: int, height: int
) -> tuple[np.ndarray, int] | None:
    """Parsuje oficjalny plik tabeli ASCII (.txt) z NASA PDS i przelicza jednostki."""
    header_lines: list[str] = []
    rows: list[list[float]] = []

    with txt_path.open("r", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                header_lines.append(s.lstrip("#").strip())
                continue
            parts = [p.strip() for p in s.split(",")]
            if len(parts) < 5:
                parts = re.split(r"[\s,;]+", s)
            try:
                vals = [float(x) for x in parts if x != ""]
                if len(vals) >= 5:
                    rows.append(vals)
            except ValueError:
                continue

    if len(rows) < 20:
        return None

    target_cols = max(set(len(r) for r in rows), key=[len(r) for r in rows].count)
    mat = np.array([r[:target_cols] for r in rows if len(r) >= target_cols], dtype=np.float64)
    lat_min, lat_max, lon_min, lon_max = mat[:, 0], mat[:, 1], mat[:, 2], mat[:, 3]

    if not (
        np.nanmin(lat_min) >= -90.5 and np.nanmax(lat_max) <= 90.5
        and np.nanmin(lon_min) >= -180.5 and np.nanmax(lon_max) <= 360.5
    ):
        return None

    val = select_measurement_column(mat, header_lines)
    val[(np.abs(val) > 1e10) | (val <= -900.0) | (val >= 9990.0)] = np.nan
    val = val * scale_factor

    lat = 0.5 * (lat_min + lat_max)
    lon = 0.5 * (lon_min + lon_max)
    grid = rasterize_points_to_equirectangular(lat, lon, val, width, height)
    return grid, len(mat)


def collect_resource_grids(
    cache_dir: Path, albedo_gray: np.ndarray
) -> dict[str, tuple[np.ndarray, str, int]]:
    """Zbiera najlepsze dostępne rastry (najwyższa rozdzielczość) dla 10 surowców LP-GRS."""
    h, w = albedo_gray.shape
    resources: dict[str, tuple[np.ndarray, str, int]] = {}

    for txt_path in sorted(cache_dir.glob("*.txt")):
        fname_l = txt_path.name.lower()
        if fname_l not in PDS_FILE_CATALOG:
            continue

        res_key, scale_factor, source_desc = PDS_FILE_CATALOG[fname_l]
        parsed = parse_nasa_pds_txt_file(txt_path, scale_factor, w, h)
        if parsed is None:
            continue

        grid, n_cells = parsed
        if res_key not in resources or n_cells > resources[res_key][2]:
            resources[res_key] = (grid, source_desc, n_cells)
            p2, p50, p98 = np.nanpercentile(grid, [2, 50, 98])
            print(
                f"[PDS OK] {res_key:6s} <- {txt_path.name:18s} "
                f"(komórek: {n_cells:6d} | mediana: {p50:7.3f} | p2..p98: {p2:7.3f} .. {p98:7.3f})"
            )

    try:
        import tifffile
        for tif_path in sorted(cache_dir.glob("*.tif*")):
            arr = tifffile.imread(tif_path).astype(np.float32)
            if arr.ndim == 3:
                arr = arr[:, :, 0]
            arr[(np.abs(arr) > 1e10) | (arr <= -900.0)] = np.nan
            arr_resized = zoom(fill_nan_nearest(arr), (h / arr.shape[0], w / arr.shape[1]), order=1)

            name_l = tif_path.stem.lower()
            for key, _, _, _ in RESOURCE_SPECS:
                if key.lower() in name_l:
                    resources[key] = (arr_resized, f"GeoTIFF ({tif_path.name})", arr.size)
                    print(f"[TIFF OK] {key:6s} <- {tif_path.name}")
    except ImportError:
        pass

    return resources


def render_resource_map(
    title: str,
    unit: str,
    cmap_name: str,
    source_label: str,
    grid: np.ndarray,
    albedo_gray: np.ndarray,
    out_path: Path,
) -> None:
    """Renderuje pojedynczą mapę equirectangular (2:1) na podkładzie albedo."""
    vmin, vmax = np.nanpercentile(grid, [2, 98])
    if np.isclose(vmin, vmax):
        vmin, vmax = float(np.nanmin(grid)), float(np.nanmax(grid) + 1e-6)

    norm_grid = np.clip((grid - vmin) / (vmax - vmin + 1e-9), 0.0, 1.0)
    cmap = plt.get_cmap(cmap_name)
    rgba = cmap(norm_grid)

    shade = 0.40 + 0.60 * albedo_gray[:, :, None]
    shaded_rgb = np.clip(rgba[:, :, :3] * shade, 0.0, 1.0)

    fig = plt.figure(figsize=(12, 6.6), dpi=150, facecolor="#111111")
    ax = fig.add_axes([0.05, 0.14, 0.90, 0.76])

    ax.imshow(
        shaded_rgb,
        extent=[-180, 180, -90, 90],
        origin="upper",
        aspect="auto",
    )

    ax.set_xticks(np.arange(-180, 181, 30))
    ax.set_yticks(np.arange(-90, 91, 30))
    ax.grid(color="white", linestyle=":", linewidth=0.5, alpha=0.35)
    ax.tick_params(colors="#dddddd", labelsize=8)
    ax.set_xlabel("Długość selenograficzna [°]", color="#dddddd", fontsize=9)
    ax.set_ylabel("Szerokość selenograficzna [°]", color="#dddddd", fontsize=9)
    ax.set_title(
        f"{title} — odwzorowanie Equirectangular (2:1)",
        color="white",
        fontsize=12,
        fontweight="bold",
        pad=10,
    )

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
    sm.set_array([])
    cbar_ax = fig.add_axes([0.15, 0.05, 0.70, 0.025])
    cbar = fig.colorbar(sm, cax=cbar_ax, orientation="horizontal")
    cbar.set_label(f"{title} [{unit}]  |  Źródło: {source_label}", color="#eeeeee", fontsize=9)
    cbar.ax.tick_params(colors="#dddddd", labelsize=8)
    cbar.outline.set_edgecolor("#666666")

    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[ZAPISANO] {out_path}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    albedo_gray, width, height = load_base_albedo(BASE_IMAGE_PATH)
    print(f"[PODKŁAD] {BASE_IMAGE_PATH} ({width}x{height} px)")

    discover_and_download_pds_files(DATA_CACHE_DIR)
    resources = collect_resource_grids(DATA_CACHE_DIR, albedo_gray)

    if not resources:
        raise RuntimeError(
            f"Nie udało się sparsować żadnego pliku zasobów w '{DATA_CACHE_DIR}'."
        )

    for key, title, unit, cmap_name in RESOURCE_SPECS:
        if key not in resources:
            print(f"[POMINIĘTO] Brak pliku źródłowego dla {key}.")
            continue
        grid, source_label, _ = resources[key]
        out_file = OUTPUT_DIR / f"moon_map_{key.lower()}_equirectangular.png"
        render_resource_map(
            title=title,
            unit=unit,
            cmap_name=cmap_name,
            source_label=source_label,
            grid=grid,
            albedo_gray=albedo_gray,
            out_path=out_file,
        )


if __name__ == "__main__":
    main()
