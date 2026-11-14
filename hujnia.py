import os
import sys
import csv
import math
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pygame

# --- STAŁE ASTRONOMICZNE (w kilometrach) ---
R_MOON = 1737.4   # Średni promień Księżyca w km
R_EARTH = 6371.0  # Promień Ziemi w km
R_SUN = 696340.0  # Promień Słońca w km

I_MOON = math.radians(1.5424)  # Nachylenie równika księżycowego do ekliptyki
SIDEREAL_MONTH = 27.321661     # dni
J2000 = datetime(2000, 1, 1, 12, 0, 0)

# Globalny zakres wysokości mapy NASA LRO LOLA DEM (w km względem R_MOON)
LOLA_MIN_KM = -9.12
LOLA_MAX_KM = 10.76

# Pełnowymiarowe produkty NASA SVS CGI Moon Kit.
# DEM: wartości float w kilometrach względem promienia referencyjnego 1737.4 km.
LOLA_DEM_URLS = [
    "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/ldem_16.tif",
    # Awaryjna mapa 8-bit, gdyby nie udało się odczytać TIFF.
    "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/ldem_3_8bit.jpg",
]

# Mapa 2025: pełna mapa 8K, 16-bit sRGB. Alternatywnie pełna mapa 2019 8K RGB.
LRO_COLOR_URLS = [
    "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_16bit_srgb_8k.tif",
    "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_8k.tif",
    "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_2k.jpg",
]


EARTH_DAY_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/Blue_Marble_2002.png/1280px-Blue_Marble_2002.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Equirectangular_projection_SW.jpg/1280px-Equirectangular_projection_SW.jpg",
]


def _download_first_available(urls, dest_path, label):
    """Pobiera pierwszy dostępny plik, zapisując go atomowo (bez cache niepełnego pobrania)."""
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return True

    for url in urls:
        temp_path = dest_path + ".part"
        try:
            print(f"[POBIERANIE] {label}: {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "LunarStellarium/2.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(temp_path, "wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            if os.path.getsize(temp_path) == 0:
                raise IOError("Pobrany plik jest pusty")
            os.replace(temp_path, dest_path)
            print(f"[OK] Zapisano: {dest_path} ({os.path.getsize(dest_path) / 1024**2:.1f} MB)")
            return True
        except Exception as e:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            print(f"[OSTRZEŻENIE] Nie udało się pobrać {label} z {url}: {e}")
    return False


def _read_tiff_array(path):
    """Odczytuje TIFF bez redukowania float/uint16 do 8 bitów, gdy tifffile jest dostępne."""
    try:
        import tifffile
        return tifffile.imread(path)
    except ImportError:
        # Pillow jest użytecznym fallbackiem; dla dokładnego DEM float32 zalecane jest tifffile.
        try:
            from PIL import Image
            with Image.open(path) as image:
                return np.asarray(image)
        except Exception as exc:
            raise RuntimeError(
                "Nie mogę odczytać TIFF. Zainstaluj pełny dekoder: python -m pip install tifffile"
            ) from exc


def _load_lunar_dem_image(path):
    """Wczytuje DEM NASA w jednostkach km względem promienia 1737.4 km."""
    if path.lower().endswith((".tif", ".tiff")):
        arr = np.asarray(_read_tiff_array(path))
        arr = np.squeeze(arr)
        if arr.ndim != 2:
            raise ValueError(f"DEM powinien być jednowymiarową siatką 2D, otrzymano {arr.shape}")

        if np.issubdtype(arr.dtype, np.floating):
            # NASA ldem_16.tif: wartości float w kilometrach.
            dem = arr.astype(np.float32)
        elif arr.dtype == np.uint16:
            # Wariant uint NASA: offset +20000, jednostka 0.5 m.
            dem = arr.astype(np.float32) / 2000.0 - 10.0
        elif arr.dtype == np.int16:
            # Surowe LOLA signed integer: jednostka 0.5 m względem R=1737.4 km.
            dem = arr.astype(np.float32) / 2000.0
        else:
            raise ValueError(f"Nieobsługiwany typ danych DEM: {arr.dtype}")
        if not np.all(np.isfinite(dem)):
            raise ValueError("DEM zawiera NaN lub nieskończoności")
        return dem.astype(np.float32, copy=False)

    # Stary obraz JPG jest wyłącznie awaryjnym, 8-bitowym przybliżeniem wysokości.
    surf = pygame.image.load(path)
    arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)
    gray = arr[:, :, 0].astype(np.float32)
    return (LOLA_MIN_KM + (gray / 255.0) * (LOLA_MAX_KM - LOLA_MIN_KM)).astype(np.float32)


def _load_lunar_color_image(path):
    """Zwraca barwną mapę jako uint8 RGB bez sztucznego spłaszczania kontrastu."""
    if path.lower().endswith((".tif", ".tiff")):
        arr = np.asarray(_read_tiff_array(path))
    else:
        surf = pygame.image.load(path)
        arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)

    arr = np.squeeze(arr)
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=2)
    elif arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
        arr = np.moveaxis(arr, 0, -1)
    if arr.ndim != 3 or arr.shape[-1] < 3:
        raise ValueError(f"Nieobsługiwany kształt mapy barwnej: {arr.shape}")

    arr = arr[..., :3]
    if arr.dtype == np.uint16:
        # Renderer i tak zapisuje obraz w 8 bitach; bierzemy 8 najbardziej znaczących bitów.
        arr = np.right_shift(arr, 8).astype(np.uint8)
    elif np.issubdtype(arr.dtype, np.integer):
        max_value = float(np.iinfo(arr.dtype).max)
        if max_value > 255.0:
            arr = np.rint(arr.astype(np.float32) * (255.0 / max_value))
    else:
        # TIFF float może przechowywać sRGB jako wartości [0,1].
        arr = np.rint(np.clip(arr.astype(np.float32), 0.0, 1.0) * 255.0)
    return np.clip(arr, 0, 255).astype(np.uint8)


def generate_fallback_lunar_dem(H=720, W=1440):
    """Generuje zapasową globalną mapę wysokości Księżyca (w km), gdy brak sieci."""
    lat_1d = np.linspace(np.pi / 2, -np.pi / 2, H)
    lon_1d = np.linspace(-np.pi, np.pi, W)
    lat = lat_1d[:, None]
    lon = lon_1d[None, :]

    x = np.cos(lat) * np.cos(lon)
    y = np.cos(lat) * np.sin(lon)
    z = np.sin(lat)

    dem = (-1.8 * x + 0.8 * np.sin(2.0 * lon) * np.cos(lat) - 1.2 * z * (z < -0.5)).astype(np.float32)

    def add_crater(clat_deg, clon_deg, brad_deg, depth_km):
        clat_r, clon_r = math.radians(clat_deg), math.radians(clon_deg)
        bx, by, bz = (
            math.cos(clat_r) * math.cos(clon_r),
            math.cos(clat_r) * math.sin(clon_r),
            math.sin(clat_r),
        )
        max_r = brad_deg * 1.3
        r_min = max(0, int((90.0 - (clat_deg + max_r)) / 180.0 * H))
        r_max = min(H, int((90.0 - (clat_deg - max_r)) / 180.0 * H) + 2)
        if r_min >= r_max:
            return
        cos_ang = np.clip(x[r_min:r_max] * bx + y[r_min:r_max] * by + z[r_min:r_max] * bz, -1.0, 1.0)
        ang_deg = np.degrees(np.arccos(cos_ang))
        inside = ang_deg < brad_deg
        rim = (ang_deg >= brad_deg) & (ang_deg < brad_deg * 1.25)
        sub_dem = dem[r_min:r_max]
        sub_dem[inside] += depth_km * (1.0 - (ang_deg[inside] / brad_deg) ** 2)
        sub_dem[rim] += -depth_km * 0.25 * np.sin((ang_deg[rim] - brad_deg) / (0.25 * brad_deg) * np.pi)

    basins = [
        (32.8, -15.6, 18.0, -3.8),   # Mare Imbrium
        (28.0, 17.5, 11.0, -3.2),    # Mare Serenitatis
        (8.5, 31.4, 12.0, -2.9),     # Mare Tranquillitatis
        (17.0, 59.1, 8.5, -3.5),     # Mare Crisium
        (-19.4, -92.8, 15.0, -4.2),  # Mare Orientale
        (-53.0, -169.0, 38.0, -6.5), # South Pole-Aitken
        (-43.3, -11.2, 3.2, -2.5),   # Tycho
        (9.6, -20.1, 3.0, -2.3),     # Copernicus
        (-89.9, 0.0, 1.8, -3.2),     # Shackleton
    ]
    for b in basins:
        add_crater(*b)

    rng = np.random.default_rng(42)
    for _ in range(450):
        clat_deg = math.degrees(math.asin(rng.uniform(-1, 1)))
        clon_deg = rng.uniform(-180.0, 180.0)
        crad_deg = rng.uniform(0.5, 5.0)
        add_crater(clat_deg, clon_deg, crad_deg, -0.35 * crad_deg)

    return dem


def generate_fallback_lunar_albedo(dem_km: np.ndarray) -> np.ndarray:
    """Tworzy mapę tekstury albedo Księżyca (morza bazaltowe, wyżyny, promienie kraterów)."""
    H, W = dem_km.shape
    lat = np.linspace(np.pi / 2, -np.pi / 2, H)[:, None]
    lon = np.linspace(-np.pi, np.pi, W)[None, :]

    base = np.clip(0.145 + 0.018 * dem_km, 0.065, 0.24)
    mottle = (
        0.015 * np.sin(lat * 18.0) * np.cos(lon * 22.0)
        + 0.010 * np.cos(lat * 47.0 - lon * 39.0)
    )
    lum = np.clip(base + mottle, 0.055, 0.27)

    for rlat_d, rlon_d, max_r, rays_n in [(-43.31, -11.36, 0.55, 14), (9.62, -20.08, 0.35, 12)]:
        rlat, rlon = math.radians(rlat_d), math.radians(rlon_d)
        dlat = lat - rlat
        dlon = (lon - rlon) * np.cos(rlat)
        dist = np.hypot(dlat, dlon)
        ang = np.arctan2(dlat, dlon)
        ray_pat = np.maximum(0.0, np.cos(ang * rays_n + np.sin(dist * 25.0))) ** 4
        lum += 0.055 * ray_pat * np.exp(-dist / (max_r * 0.45)) * (dist < max_r)

    albedo_rgb = np.stack([lum * 1.04, lum * 1.00, lum * 0.93], axis=-1).astype(np.float32)
    return np.clip(albedo_rgb, 0.04, 0.34)


def load_or_download_lunar_maps():
    """Wczytuje pełne mapy NASA; nie wygładza DEM ani nie uśrednia kolorów."""
    os.makedirs("Textures", exist_ok=True)

    # Nowe nazwy cache celowo omijają moon_*_v2.npy zawierające stare, wygładzone dane.
    dem_cache = os.path.join("Textures", "moon_dem_nasa_16ppd_v3.npy")
    dem_source_cache = dem_cache + ".source"
    color_cache = os.path.join("Textures", "moon_color_nasa_8k_v3.npy")
    dem_path = os.path.join("Textures", "moon_dem_16ppd.tif")
    dem_jpg_path = os.path.join("Textures", "moon_dem_fallback.jpg")
    color_path = os.path.join("Textures", "moon_color_8k.tif")
    color_jpg_path = os.path.join("Textures", "moon_color_fallback.jpg")

    # DEM: NASA LDEM_16 to rastrowa mapa float w kilometrach, bez stratnego JPEG-a.
    if os.path.exists(dem_cache):
        dem = np.load(dem_cache).astype(np.float32, copy=False)
        try:
            with open(dem_source_cache, "r", encoding="utf-8") as source_file:
                dem_src = source_file.read().strip() or "DEM z lokalnego cache"
        except OSError:
            dem_src = "DEM z lokalnego cache"
    else:
        if not os.path.exists(dem_path):
            _download_first_available(LOLA_DEM_URLS[:1], dem_path, "NASA LOLA LDEM 16 px/deg")
        if os.path.exists(dem_path):
            try:
                dem = _load_lunar_dem_image(dem_path)
                dem_src = "NASA LOLA LDEM 16 px/deg (bez wygładzania)"
            except Exception as exc:
                print(f"[OSTRZEŻENIE] Nie udało się odczytać pełnego DEM: {exc}")
                try:
                    os.remove(dem_path)
                except OSError:
                    pass
                dem = None
        else:
            dem = None

        if dem is None:
            # Zapasowo pobieramy osobny JPG pod właściwym rozszerzeniem.
            if not os.path.exists(dem_jpg_path):
                _download_first_available(LOLA_DEM_URLS[1:], dem_jpg_path, "awaryjny 8-bitowy DEM NASA")
            if os.path.exists(dem_jpg_path):
                try:
                    dem = _load_lunar_dem_image(dem_jpg_path)
                    dem_src = "NASA LOLA DEM (awaryjny JPG 8-bit)"
                except Exception as exc:
                    print(f"[OSTRZEŻENIE] Nie udało się odczytać awaryjnego DEM: {exc}")
                    dem = None
            if dem is None:
                dem = generate_fallback_lunar_dem()
                dem_src = "Proceduralny DEM (awaryjny)"
        np.save(dem_cache, dem.astype(np.float32))
        with open(dem_source_cache, "w", encoding="utf-8") as source_file:
            source_file.write(dem_src)

    # Mapa barwna: priorytet ma mapa NASA 2025 8K, a następnie pełna mapa 2019 8K.
    if os.path.exists(color_cache):
        albedo_rgb = np.load(color_cache)
    else:
        if not os.path.exists(color_path):
            _download_first_available(LRO_COLOR_URLS[:2], color_path, "NASA LROC color map 8K")

        if os.path.exists(color_path):
            try:
                albedo_rgb = _load_lunar_color_image(color_path)
                print(f"[OK] Wczytano mapę barwną NASA: {color_path} ({albedo_rgb.shape[1]}x{albedo_rgb.shape[0]})")
            except Exception as exc:
                print(f"[OSTRZEŻENIE] Nie udało się odczytać pełnej mapy barwnej: {exc}")
                try:
                    os.remove(color_path)
                except OSError:
                    pass
                albedo_rgb = None
        else:
            albedo_rgb = None

        if albedo_rgb is None:
            if not os.path.exists(color_jpg_path):
                _download_first_available(LRO_COLOR_URLS[2:], color_jpg_path, "awaryjna mapa barwna NASA")
            if os.path.exists(color_jpg_path):
                try:
                    albedo_rgb = _load_lunar_color_image(color_jpg_path)
                except Exception as exc:
                    print(f"[OSTRZEŻENIE] Nie udało się odczytać awaryjnej mapy barwnej: {exc}")
                    albedo_rgb = None

        if albedo_rgb is None:
            # Ostatnia możliwość: tekstura lokalna użytkownika lub widoczny fallback proceduralny.
            custom_tex = next(
                (p for p in [
                    "Textures/moon_color8K.jpg", "Textures/moon_color8K.png",
                    "Textures/moon_albedo.jpg", "Textures/moon_color.jpg",
                ] if os.path.exists(p)),
                None,
            )
            if custom_tex is not None:
                try:
                    albedo_rgb = _load_lunar_color_image(custom_tex)
                    print(f"[OK] Wczytano lokalną teksturę Księżyca: {custom_tex}")
                except Exception:
                    albedo_rgb = None
            if albedo_rgb is None:
                albedo_rgb = generate_fallback_lunar_albedo(dem)

        # Cache jest uint8 RGB, ale zachowuje pełny raster i nie stosuje rozmycia.
        if albedo_rgb.dtype == np.uint8:
            np.save(color_cache, albedo_rgb)

    return dem, albedo_rgb, dem_src


def load_earth_textures():
    """Wczytuje tekstury Ziemi lub pobiera globalną mapę Blue Marble, jeśli brak plików lokalnych."""
    os.makedirs("Textures", exist_ok=True)
    day_candidates = [
        "Textures/earth_day8K.jpg",
        "Textures/earth_day8K.png",
        "Textures/earth_day.jpg",
        "Textures/earth_day.png",
    ]
    day_path = next((p for p in day_candidates if os.path.exists(p)), None)
    if day_path is None:
        dl_path = "Textures/earth_day.jpg"
        if _download_first_available(EARTH_DAY_URLS, dl_path, "Tekstura Ziemi (Blue Marble)"):
            day_path = dl_path

    night_path = next((p for p in ["Textures/earth_night8K.jpg", "Textures/earth_night8K.png", "Textures/earth_night.jpg"] if os.path.exists(p)), None)
    clouds_path = next((p for p in ["Textures/earth_clouds8K.jpg", "Textures/earth_clouds8K.png", "Textures/earth_clouds.jpg"] if os.path.exists(p)), None)

    def _to_rgb_array(path):
        if not path:
            return None
        try:
            surf = pygame.image.load(path).convert()
            print(f"[OK] Wczytano teksturę Ziemi: {path}")
            return pygame.surfarray.array3d(surf).transpose(1, 0, 2)
        except Exception as e:
            print(f"[OSTRZEŻENIE] Błąd wczytywania {path}: {e}")
            return None

    return _to_rgb_array(day_path), _to_rgb_array(night_path), _to_rgb_array(clouds_path)


class LunarTerrain3D:
    """Renderer terenu księżycowego próbkowany nearest-neighbour z map NASA."""

    LUT_SIZE = 4096

    def __init__(self, dem_km: np.ndarray, albedo_rgb: np.ndarray):
        self.dem = dem_km
        self.H, self.W = dem_km.shape
        # uint8 oznacza rzeczywistą mapę RGB NASA. Zachowujemy jej kanały i proporcje;
        # jeden globalny mnożnik ekspozycji kompensuje skalę oświetlenia shadera.
        if albedo_rgb.dtype == np.uint8:
            self.albedo_map = albedo_rgb
            self.albedo_is_uint8 = True
            self.albedo_gain = 0.28
        else:
            # Mapa proceduralna fallbacku jest już w skali używanej przez shader.
            self.albedo_map = albedo_rgb.astype(np.float32)
            self.albedo_is_uint8 = False
            self.albedo_gain = 1.0
        self.AH, self.AW = self.albedo_map.shape[:2]

        # Gęstsza siatka polarna ogranicza utratę detali przed próbkowaniem obrazu.
        self.n_r = 512
        self.n_az = 1440
        self.az_grid = np.linspace(0.0, 2.0 * np.pi, self.n_az + 1, dtype=np.float32)
        self.radii_km = None

        self.max_r_km = 220.0
        self.inv_sqrt_scale = 1.0
        self.lut_idx_lo = None
        self.lut_wr = None

        self.cached_state = None
        self.h_polar = None
        self.alb_polar = None
        self.norm_polar = None
        self.horizon_alt = None
        self.sin_hor_az = None
        self.hor_dist_az = None
        self.obs_elev_km = 0.0
        self.obs_radius_km = R_MOON
        self.alt_above_km = 0.002

    def _build_polar_and_lut(self, alt_above_surface_km: float):
        h_safe = max(0.0005, alt_above_surface_km)
        hor_dist = math.sqrt(max(0.0, (R_MOON + h_safe) ** 2 - R_MOON ** 2))
        max_r = max(220.0, hor_dist + 160.0)
        inner_step = min(0.0004, h_safe * 0.2)
        self.radii_km = np.concatenate(([0.0], np.geomspace(inner_step, max_r, self.n_r - 1))).astype(np.float32)
        self.max_r_km = max_r

        sqrt_max = math.sqrt(max_r)
        sqrt_grid = np.linspace(0.0, sqrt_max, self.LUT_SIZE, dtype=np.float32)
        r_lut = sqrt_grid * sqrt_grid
        idx_hi = np.clip(np.searchsorted(self.radii_km, r_lut, side="right"), 1, self.n_r - 1)
        idx_lo = idx_hi - 1
        r_lo = self.radii_km[idx_lo]
        r_hi = self.radii_km[idx_hi]

        self.inv_sqrt_scale = (self.LUT_SIZE - 1) / sqrt_max
        self.lut_idx_lo = idx_lo.astype(np.int32)
        self.lut_wr = np.clip((r_lut - r_lo) / np.maximum(r_hi - r_lo, 1e-9), 0.0, 1.0).astype(np.float32)

    def sample_dem_nearest(self, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
        """Próbkuje komórkę źródłowego rastra DEM bez interpolacji i bez dodawania detali."""
        fy = np.clip((90.0 - lat_deg) / 180.0 * self.H, 0.0, self.H - 1.0)
        lon_wrapped = ((lon_deg + 180.0) % 360.0) - 180.0
        fx = ((lon_wrapped + 180.0) / 360.0 * self.W) % self.W
        iy = np.floor(fy).astype(np.int32)
        ix = np.floor(fx).astype(np.int32)
        return self.dem[iy, ix].astype(np.float32, copy=False)

    def sample_albedo_nearest(self, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
        """Próbkuje dokładny piksel mapy RGB; brak bilinearnego mieszania sąsiednich barw."""
        fy = np.clip((90.0 - lat_deg) / 180.0 * self.AH, 0.0, self.AH - 1.0)
        lon_wrapped = ((lon_deg + 180.0) % 360.0) - 180.0
        fx = ((lon_wrapped + 180.0) / 360.0 * self.AW) % self.AW
        iy = np.floor(fy).astype(np.int32)
        ix = np.floor(fx).astype(np.int32)
        sampled = self.albedo_map[iy, ix]
        if self.albedo_is_uint8:
            return sampled.astype(np.float32) / 255.0
        return sampled.astype(np.float32, copy=False)

    def update_observer(self, lat_deg: float, lon_deg: float, alt_above_surface_km: float = 0.002):
        state_key = (round(lat_deg, 5), round(lon_deg, 5), round(alt_above_surface_km, 6))
        if self.cached_state == state_key:
            return
        self.cached_state = state_key
        self.alt_above_km = alt_above_surface_km

        self._build_polar_and_lut(alt_above_surface_km)

        ground_h = float(self.sample_dem_nearest(np.array([lat_deg]), np.array([lon_deg]))[0])
        self.obs_elev_km = ground_h
        self.obs_radius_km = R_MOON + ground_h + alt_above_surface_km

        lat0 = math.radians(lat_deg)
        lon0 = math.radians(lon_deg)
        up0 = np.array([math.cos(lat0) * math.cos(lon0), math.cos(lat0) * math.sin(lon0), math.sin(lat0)])
        east0 = np.array([-math.sin(lon0), math.cos(lon0), 0.0])
        north0 = np.cross(up0, east0)

        delta = (self.radii_km / R_MOON)[:, None]
        az = self.az_grid[:-1][None, :]

        u_body = (
            np.cos(delta)[..., None] * up0[None, None, :]
            + (np.sin(delta) * np.cos(az))[..., None] * north0[None, None, :]
            + (np.sin(delta) * np.sin(az))[..., None] * east0[None, None, :]
        )

        v_lat = np.degrees(np.arcsin(np.clip(u_body[..., 2], -1.0, 1.0)))
        v_lon = np.degrees(np.arctan2(u_body[..., 1], u_body[..., 0]))

        h_grid = self.sample_dem_nearest(v_lat, v_lon)
        h_grid[0, :] = ground_h
        self.h_polar = h_grid
        r_grid = R_MOON + h_grid

        p_body = r_grid[..., None] * u_body
        obs_body = self.obs_radius_km * up0
        rel_body = p_body - obs_body[None, None, :]

        rel_n = (rel_body @ north0).astype(np.float32)
        rel_e = (rel_body @ east0).astype(np.float32)
        rel_u = (rel_body @ up0).astype(np.float32)
        pts_enu = np.stack([rel_n, rel_e, rel_u], axis=-1)

        dr_vec = np.empty_like(pts_enu)
        dr_vec[:-1] = pts_enu[1:] - pts_enu[:-1]
        dr_vec[-1] = dr_vec[-2]

        daz_vec = 0.5 * (np.roll(pts_enu, -1, axis=1) - np.roll(pts_enu, 1, axis=1))
        normals = np.cross(dr_vec, daz_vec)
        norms = np.linalg.norm(normals, axis=-1, keepdims=True)
        normals = np.where(norms > 1e-9, normals / np.maximum(norms, 1e-9), np.array([0.0, 0.0, 1.0], dtype=np.float32))
        normals[0, :] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        self.norm_polar = normals.astype(np.float32)

        self.alb_polar = self.sample_albedo_nearest(v_lat, v_lon)

        dist_3d = np.linalg.norm(pts_enu[1:], axis=-1)
        elev_angles = np.arcsin(np.clip(rel_u[1:] / np.maximum(dist_3d, 1e-9), -1.0, 1.0))
        max_idx = np.argmax(elev_angles, axis=0)
        az_indices = np.arange(self.n_az)
        raw_hor = elev_angles[max_idx, az_indices]

        self.horizon_alt = (
            0.25 * np.roll(raw_hor, 1)
            + 0.50 * raw_hor
            + 0.25 * np.roll(raw_hor, -1)
        ).astype(np.float32)
        self.sin_hor_az = np.sin(self.horizon_alt).astype(np.float32)
        self.hor_dist_az = np.maximum(0.5, self.radii_km[max_idx + 1]).astype(np.float32)

    def get_horizon_at_azimuth(self, az_rad: float) -> float:
        az_ext = np.append(self.horizon_alt, self.horizon_alt[0])
        return float(np.interp(az_rad % (2.0 * np.pi), self.az_grid, az_ext))

    def draw_3d(self, screen, cw, ch, cam_alt, cam_az, fov, sun_alt, sun_az, earth_alt,
                wireframe=False, show_horizon_line=True):
        scale_div = 1.6 if max(cw, ch) >= 1100 else 1.25
        rw = max(640, int(cw / scale_div))
        rh = max(400, int(ch / scale_div))

        fwd = np.array([
            math.cos(cam_alt) * math.cos(cam_az),
            math.cos(cam_alt) * math.sin(cam_az),
            math.sin(cam_alt),
        ], dtype=np.float32)
        world_up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        right = np.cross(fwd, world_up)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([-math.sin(cam_az), math.cos(cam_az), 0.0], dtype=np.float32)
        else:
            right /= np.linalg.norm(right)
        cam_up = np.cross(right, fwd)

        focal = (rh / 2.0) / math.tan(fov / 2.0)
        xs = (np.arange(rw, dtype=np.float32) - rw / 2.0) / focal
        ys = (rh / 2.0 - np.arange(rh, dtype=np.float32)) / focal

        dx = fwd[0] + xs[None, :] * right[0] + ys[:, None] * cam_up[0]
        dy = fwd[1] + xs[None, :] * right[1] + ys[:, None] * cam_up[1]
        dz = fwd[2] + xs[None, :] * right[2] + ys[:, None] * cam_up[2]
        inv_len = 1.0 / np.sqrt(dx * dx + dy * dy + dz * dz)
        dx *= inv_len
        dy *= inv_len
        dz *= inv_len

        max_sin_hor = float(np.max(self.sin_hor_az))
        row_min_dz = np.min(dz, axis=1)
        active_rows = np.nonzero(row_min_dz <= max_sin_hor)[0]

        if len(active_rows) > 0:
            y_start = int(active_rows[0])
            dx_s = dx[y_start:]
            dy_s = dy[y_start:]
            dz_s = dz[y_start:]

            az_all = np.arctan2(dy_s, dx_s) % (2.0 * math.pi)
            az_f = az_all * (self.n_az / (2.0 * math.pi))
            az0 = az_f.astype(np.int32) % self.n_az
            az1 = (az0 + 1) % self.n_az
            waz = az_f - np.floor(az_f)

            sin_hor_px = self.sin_hor_az[az0] * (1.0 - waz) + self.sin_hor_az[az1] * waz
            edge_alpha = np.clip((sin_hor_px - dz_s) * focal * 1.4, 0.0, 1.0)
            valid = edge_alpha > 0.01

            if np.any(valid):
                dz_v = dz_s[valid]
                dx_v = dx_s[valid]
                dy_v = dy_s[valid]
                az0_v = az0[valid]
                az1_v = az1[valid]
                waz_v = waz[valid]

                # Promień odniesienia przechodzi przez lokalny poziom terenu obserwatora.
                # Dzięki temu obserwator w dnie basenu (h < 0) nie znajduje się
                # matematycznie pod powierzchnią sfery o promieniu średnim Księżyca.
                R_ref = R_MOON + self.obs_elev_km
                R_obs = self.obs_radius_km
                b = R_obs * dz_v
                c0 = R_obs * R_obs - R_ref * R_ref
                disc = np.maximum(0.0, b * b - c0)
                t_hit = -b - np.sqrt(disc)

                hor_dist_v = self.hor_dist_az[az0_v] * (1.0 - waz_v) + self.hor_dist_az[az1_v] * waz_v
                horiz_speed = np.sqrt(np.maximum(1e-8, dx_v * dx_v + dy_v * dy_v))
                hit_horizontal = np.maximum(0.0, t_hit * horiz_speed)
                hit_radial = np.maximum(1e-6, R_obs + t_hit * dz_v)
                # LUT używa odległości po powierzchni (łuku), nie rzutu na płaszczyznę.
                r_ground = R_ref * np.arctan2(hit_horizontal, hit_radial)
                r_ground = np.clip(r_ground, 0.0, hor_dist_v)

                lut_idx = np.minimum(self.LUT_SIZE - 1, (np.sqrt(r_ground) * self.inv_sqrt_scale).astype(np.int32))
                r0 = self.lut_idx_lo[lut_idx]
                r1 = np.minimum(r0 + 1, self.n_r - 1)
                wr = self.lut_wr[lut_idx]
                # Nearest-neighbour także na siatce polarnej: kolory i wysokości nie są uśredniane.
                r_near = np.where(wr < 0.5, r0, r1)
                az_near = np.where(waz_v < 0.5, az0_v, az1_v)
                base_rgb = self.alb_polar[r_near, az_near] * self.albedo_gain
                n_vec = self.norm_polar[r_near, az_near]
                n_vec = n_vec / np.maximum(np.linalg.norm(n_vec, axis=-1, keepdims=True), 1e-6)

                sun_enu = np.array([
                    math.cos(sun_alt) * math.cos(sun_az),
                    math.cos(sun_alt) * math.sin(sun_az),
                    math.sin(sun_alt),
                ], dtype=np.float32)
                # Nie zerujemy całego oświetlenia, gdy Słońce jest za lokalnym
                # horyzontem obserwatora: wyższe fragmenty terenu nadal mogą być
                # oświetlone. Każdy widoczny fragment dostaje własne N·L.
                ndotl = np.maximum(0.0, n_vec @ sun_enu)
                lunar_reflectance = (ndotl / (ndotl + 0.16)) * 1.16
                earthshine = 0.045 * max(0.0, math.sin(earth_alt))
                ambient = 0.032 + earthshine

                intensity = 165.0 * ambient + 940.0 * lunar_reflectance
                rgb_out = np.clip(base_rgb * intensity[:, None], 6, 248).astype(np.uint8)

                out_rgba = np.zeros((rh, rw, 4), dtype=np.uint8)
                sub_out = out_rgba[y_start:]
                sub_out[valid, :3] = rgb_out
                sub_out[valid, 3] = (edge_alpha[valid] * 255.0).astype(np.uint8)

                surf = pygame.image.frombuffer(out_rgba.tobytes(), (rw, rh), "RGBA")
                # Nearest-neighbour upscale celowo zachowuje piksele danych wejściowych.
                surf_full = pygame.transform.scale(surf, (cw, ch))
                screen.blit(surf_full, (0, 0))

        # Konwersja do natywnych typów float Pythona (wymagane przez pygame.draw.aalines w Python 3.13 / NumPy 2.x)
        fx, fy, fz = float(fwd[0]), float(fwd[1]), float(fwd[2])
        rx, ry, rz = float(right[0]), float(right[1]), float(right[2])
        ux, uy, uz = float(cam_up[0]), float(cam_up[1]), float(cam_up[2])
        focal_full = float((ch / 2.0) / math.tan(fov / 2.0))
        half_w = float(cw) / 2.0
        half_h = float(ch) / 2.0

        if wireframe:
            for r_val in (0.02, 0.1, 0.5, 2.0, 10.0, 50.0, 150.0):
                if r_val > self.max_r_km:
                    continue
                pts_ring = []
                for az_np in self.az_grid[::6]:
                    az_v = float(az_np)
                    pn = r_val * math.cos(az_v)
                    pe = r_val * math.sin(az_v)
                    pu = -0.5 * (r_val * r_val) / R_MOON - float(self.alt_above_km)
                    zc = pn * fx + pe * fy + pu * fz
                    if zc > 0.002:
                        xc = pn * rx + pe * ry + pu * rz
                        yc = pn * ux + pe * uy + pu * uz
                        sx = float(half_w + (xc / zc) * focal_full)
                        sy = float(half_h - (yc / zc) * focal_full)
                        if math.isfinite(sx) and math.isfinite(sy):
                            pts_ring.append((sx, sy))
                    else:
                        if len(pts_ring) > 1:
                            pygame.draw.aalines(screen, (95, 130, 165), False, pts_ring)
                        pts_ring = []
                if len(pts_ring) > 1:
                    pygame.draw.aalines(screen, (95, 130, 165), False, pts_ring)

        if show_horizon_line and self.horizon_alt is not None:
            h_pts = []
            for h_alt_np, h_az_np in zip(self.horizon_alt, self.az_grid[:-1]):
                h_alt = float(h_alt_np)
                h_az = float(h_az_np)
                px = math.cos(h_alt) * math.cos(h_az)
                py = math.cos(h_alt) * math.sin(h_az)
                pz = math.sin(h_alt)
                zc = px * fx + py * fy + pz * fz
                if zc > 0.05:
                    xc = px * rx + py * ry + pz * rz
                    yc = px * ux + py * uy + pz * uz
                    sx = float(half_w + (xc / zc) * focal_full)
                    sy = float(half_h - (yc / zc) * focal_full)
                    if math.isfinite(sx) and math.isfinite(sy):
                        h_pts.append((sx, sy))
                else:
                    if len(h_pts) > 1:
                        pygame.draw.aalines(screen, (85, 160, 210), False, h_pts)
                    h_pts = []
            if len(h_pts) > 1:
                pygame.draw.aalines(screen, (85, 160, 210), False, h_pts)


def draw_telescopic_sun(screen, sx, sy, r_sun_exact, cw, ch):
    """Renderuje Słońce z koroną i pociemnieniem brzegowym przy dowolnym powiększeniu."""
    r_sun = max(3.0, r_sun_exact)
    halo_r = int(min(max(r_sun * 2.5, 16), max(cw, ch)))

    x0 = max(0, int(sx - halo_r))
    x1 = min(cw, int(sx + halo_r) + 1)
    y0 = max(0, int(sy - halo_r))
    y1 = min(ch, int(sy + halo_r) + 1)
    if x1 <= x0 or y1 <= y0:
        return

    w_box, h_box = x1 - x0, y1 - y0
    ss = 1 if halo_r <= 180 else (2 if halo_r <= 450 else 3)

    xs = (np.linspace(x0, x1 - 1, max(2, w_box // ss), dtype=np.float32) - sx) / r_sun
    ys = (np.linspace(y0, y1 - 1, max(2, h_box // ss), dtype=np.float32) - sy) / r_sun
    gx, gy = np.meshgrid(xs, ys)
    dist = np.sqrt(gx * gx + gy * gy)

    img = np.zeros((ys.shape[0], xs.shape[0], 4), dtype=np.uint8)

    disk = dist <= 1.0
    if np.any(disk):
        mu = np.sqrt(np.clip(1.0 - dist[disk] ** 2, 0.0, 1.0))
        limb_dark = 0.42 + 0.58 * np.power(mu, 0.55)
        if r_sun > 18.0:
            granulation = 0.028 * np.sin(gx[disk] * 55.0) * np.cos(gy[disk] * 55.0)
            limb_dark = np.clip(limb_dark + granulation, 0.25, 1.05)
        img[disk, 0] = np.clip(255.0 * np.minimum(1.0, limb_dark * 1.06), 0, 255).astype(np.uint8)
        img[disk, 1] = np.clip(246.0 * limb_dark, 0, 255).astype(np.uint8)
        img[disk, 2] = np.clip(218.0 * np.power(limb_dark, 1.15), 0, 255).astype(np.uint8)
        img[disk, 3] = 255

    corona = (~disk) & (dist <= 2.5)
    if np.any(corona):
        t_c = (dist[corona] - 1.0) / 1.5
        glow = np.exp(-3.4 * t_c) * (1.0 - t_c)
        img[corona, 0] = 255
        img[corona, 1] = 225
        img[corona, 2] = 155
        img[corona, 3] = np.clip(195.0 * glow, 0, 255).astype(np.uint8)

    surf = pygame.image.frombuffer(img.tobytes(), (xs.shape[0], ys.shape[0]), "RGBA")
    if ss > 1:
        surf = pygame.transform.smoothscale(surf, (w_box, h_box))
    screen.blit(surf, (x0, y0))


def get_camera_basis(cam_alt, cam_az):
    """Zwraca osie kamery w lokalnym układzie ENU (N, E, U)."""
    fwd = np.array([
        math.cos(cam_alt) * math.cos(cam_az),
        math.cos(cam_alt) * math.sin(cam_az),
        math.sin(cam_alt),
    ], dtype=np.float64)
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(fwd, world_up)
    if np.linalg.norm(right) < 1e-10:
        right = np.array([-math.sin(cam_az), math.cos(cam_az), 0.0], dtype=np.float64)
    else:
        right /= np.linalg.norm(right)
    cam_up = np.cross(right, fwd)
    cam_up /= max(np.linalg.norm(cam_up), 1e-10)
    return fwd, right, cam_up


def draw_telescopic_earth(
    screen, ex, ey, r_earth_exact, cw, ch,
    earth_view_body, camera_right_body, camera_up_body,
    sun_from_earth_body, earth_axes_body,
    day_arr=None, night_arr=None, clouds_arr=None,
):
    """Rysuje glob Ziemi z prawidłową geometrią fazy i oświetlenia.

    Wszystkie wektory (widok, kamera, Słońce i osie Ziemi) są w jednym
    księżycowym układzie selenograficznym. Współrzędne tekstury są obliczane
    w obróconym układzie ziemskim: długość geograficzna Greenwich obraca się
    z rzeczywistym dniem gwiazdowym.
    """
    r_earth = max(4.0, float(r_earth_exact))
    pad = int(max(3, r_earth * 0.05))
    r_outer = r_earth + pad

    x0 = max(0, int(ex - r_outer))
    x1 = min(cw, int(ex + r_outer) + 1)
    y0 = max(0, int(ey - r_outer))
    y1 = min(ch, int(ey + r_outer) + 1)
    if x1 <= x0 or y1 <= y0:
        return

    w_box, h_box = x1 - x0, y1 - y0
    ss = 1 if r_earth <= 160 else (2 if r_earth <= 420 else 3)
    nx = max(2, w_box // ss)
    ny = max(2, h_box // ss)
    xs = (np.linspace(x0, x1 - 1, nx, dtype=np.float32) - ex) / r_earth
    ys = (np.linspace(y0, y1 - 1, ny, dtype=np.float32) - ey) / r_earth
    gx, gy = np.meshgrid(xs, ys)
    dist_sq = gx * gx + gy * gy
    mask = dist_sq <= 1.0
    if not np.any(mask):
        return

    gz = np.zeros_like(dist_sq, dtype=np.float32)
    gz[mask] = np.sqrt(np.maximum(0.0, 1.0 - dist_sq[mask]))

    view = np.asarray(earth_view_body, dtype=np.float64)
    view /= np.linalg.norm(view)
    right = np.asarray(camera_right_body, dtype=np.float64)
    right = right - np.dot(right, view) * view
    right_norm = np.linalg.norm(right)
    if right_norm < 1e-10:
        up_try = np.asarray(camera_up_body, dtype=np.float64)
        up_try = up_try - np.dot(up_try, view) * view
        up_try /= max(np.linalg.norm(up_try), 1e-10)
        right = np.cross(view, up_try)
        right /= max(np.linalg.norm(right), 1e-10)
    else:
        right /= right_norm
    up = np.cross(right, view)
    up /= max(np.linalg.norm(up), 1e-10)
    if np.dot(up, camera_up_body) < 0.0:
        right = -right
        up = -up

    # Normalne pikseli tarczy Ziemi w przestrzeni 3D: widoczna półkula,
    # a nie sztuczna kula z oświetleniem liczonym w układzie ekranu.
    n_body = (
        gz[mask, None] * view[None, :]
        + gx[mask, None] * right[None, :]
        + gy[mask, None] * up[None, :]
    )

    earth_x, earth_y, earth_z = (np.asarray(v, dtype=np.float64) for v in earth_axes_body)
    nx_ecef = n_body @ earth_x
    ny_ecef = n_body @ earth_y
    nz_ecef = np.clip(n_body @ earth_z, -1.0, 1.0)
    lat_pt = np.arcsin(nz_ecef)
    lon_pt = np.arctan2(ny_ecef, nx_ecef)

    u = (lon_pt + np.pi) / (2.0 * np.pi)
    v = (np.pi * 0.5 - lat_pt) / np.pi

    if day_arr is not None:
        dh, dw = day_arr.shape[:2]
        tx = (u * dw).astype(np.int32) % dw
        ty = np.clip((v * dh).astype(np.int32), 0, dh - 1)
        rgb = day_arr[ty, tx].astype(np.float32)
    else:
        continent = (
            np.sin(lon_pt * 2.1 + 0.4) * np.cos(lat_pt * 2.3)
            + 0.55 * np.cos(lon_pt * 4.7 - 1.1) * np.sin(lat_pt * 3.8 + 0.3)
            + 0.30 * np.sin(lon_pt * 9.0 + lat_pt * 7.0)
        )
        is_land = continent > 0.18
        is_ice = np.abs(lat_pt) > np.radians(72.0 - 8.0 * continent)
        rgb = np.empty((n_body.shape[0], 3), dtype=np.float32)
        rgb[:] = (22.0, 72.0, 158.0)
        rgb[is_land] = (64.0, 118.0, 62.0)
        rgb[is_ice] = (235.0, 242.0, 248.0)

    sun_dir = np.asarray(sun_from_earth_body, dtype=np.float64)
    sun_dir /= np.linalg.norm(sun_dir)
    cos_sun = np.clip(n_body @ sun_dir, -1.0, 1.0)
    day_side = cos_sun > 0.0
    out_rgb = np.zeros_like(rgb)

    if np.any(day_side):
        if clouds_arr is not None:
            ch_t, cw_t = clouds_arr.shape[:2]
            cx = (u[day_side] * cw_t).astype(np.int32) % cw_t
            cy = np.clip((v[day_side] * ch_t).astype(np.int32), 0, ch_t - 1)
            cf = (clouds_arr[cy, cx, 0].astype(np.float32) / 255.0) * 0.75
            rgb[day_side] = rgb[day_side] * (1.0 - cf[:, None]) + 255.0 * cf[:, None]
        # Jasność zanika dokładnie na terminatorze, więc faza pokrywa się
        # z kątem między kierunkiem Ziemia->obserwator i Ziemia->Słońce.
        factor = np.power(np.maximum(cos_sun[day_side], 0.0), 0.62)[:, None]
        out_rgb[day_side] = rgb[day_side] * factor

    if np.any(~day_side):
        n_idx = ~day_side
        if night_arr is not None:
            nh, nw = night_arr.shape[:2]
            nx = (u[n_idx] * nw).astype(np.int32) % nw
            ny = np.clip((v[n_idx] * nh).astype(np.int32), 0, nh - 1)
            out_rgb[n_idx] = night_arr[ny, nx].astype(np.float32)
        else:
            out_rgb[n_idx] = rgb[n_idx] * 0.035

    # Cienka poświata atmosferyczna na brzegu tarczy.
    limb = np.power(np.clip(1.0 - gz[mask], 0.0, 1.0), 3.0) * np.clip(cos_sun + 0.25, 0.0, 1.0)
    out_rgb[:, 0] += 55.0 * limb
    out_rgb[:, 1] += 115.0 * limb
    out_rgb[:, 2] += 205.0 * limb

    img = np.zeros((ny, nx, 4), dtype=np.uint8)
    img[mask, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    img[mask, 3] = 255

    surf = pygame.image.frombuffer(img.tobytes(), (nx, ny), "RGBA")
    if ss > 1:
        # Tarcza mapy Ziemi może pozostać gładka; tekstura Księżyca ma osobny
        # tryb pikselowy i jest skalowana najbliższym sąsiadem.
        surf = pygame.transform.smoothscale(surf, (w_box, h_box))
    screen.blit(surf, (x0, y0))


def load_year_data(year):
    """Wczytuje geocentryczne wektory Słońca i Księżyca w ekliptyce J2000.

    Obsługiwane są obie konwencje katalogu: Coords/ (jak w starszym programie)
    i coords/ (jak w nowszych skryptach).
    Wiersz CSV: czas UTC, Sun X/Y/Z, Moon X/Y/Z.
    Jednostki wejściowe mogą być km, m albo AU.
    """
    candidates = [Path("Coords") / f"{year}.csv", Path("coords") / f"{year}.csv"]
    filepath = next((p for p in candidates if p.is_file()), None)

    if filepath is not None:
        times = []
        rows = []
        with filepath.open(mode="r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for line_no, row in enumerate(reader, start=2):
                if not row or not any(cell.strip() for cell in row):
                    continue
                if len(row) < 7:
                    raise ValueError(
                        f"{filepath}:{line_no}: oczekiwano 7 kolumn (czas + 6 współrzędnych), "
                        f"otrzymano {len(row)}"
                    )
                try:
                    t = datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M:%S")
                    xyz = [float(value) for value in row[1:7]]
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Nieprawidłowy wiersz {filepath}:{line_no}: {row}") from exc
                times.append(t)
                rows.append(xyz)

        if not rows:
            raise ValueError(f"Plik ephemeryd jest pusty: {filepath}")
        coords = np.asarray(rows, dtype=np.float64)

        mean_moon_dist = float(np.mean(np.linalg.norm(coords[:, 3:6], axis=1)))
        # JPL Horizons potrafi zwracać wektory w km, m albo AU.
        if mean_moon_dist > 1.0e7:
            coords *= 0.001                 # metry -> kilometry
        elif 1.0e-5 < mean_moon_dist < 1.0:
            coords *= 149597870.7           # AU -> kilometry

        print(f"[OK] Wczytano dane dla roku {year} z: {filepath} (odległość Księżyca ~{mean_moon_dist:g} w pliku)")
    else:
        print(f"[OSTRZEŻENIE] Nie znaleziono Coords/{year}.csv ani coords/{year}.csv. "
              f"Generuję przybliżone dane testowe dla roku {year}...")
        start_dt = datetime(year, 1, 1, 0, 0, 0)
        end_dt = datetime(year + 1, 1, 1, 0, 0, 0)
        n_hours = int((end_dt - start_dt).total_seconds() // 3600)
        times = [start_dt + timedelta(hours=h) for h in range(n_hours)]
        t_days = np.array([(t - J2000).total_seconds() / 86400.0 for t in times], dtype=np.float64)

        # Przybliżony geocentryczny wektor Słońca. Faza jest zakotwiczona
        # w długości średniej Słońca na epokę J2000, a nie w arbitralnym kącie.
        sun_lon = np.radians(280.46061837 + 0.98564736 * t_days)
        sun_dist = 149597870.7
        sun_x = sun_dist * np.cos(sun_lon)
        sun_y = sun_dist * np.sin(sun_lon)
        sun_z = np.zeros_like(t_days)

        # Średnia długość i argument szerokości Księżyca; wystarczająco dobre
        # do działania awaryjnego, gdy nie ma precyzyjnych wektorów Horizons.
        moon_lon = np.radians(218.3164477 + 13.17639648 * t_days)
        moon_F = np.radians(93.2720950 + 13.22935024 * t_days)
        moon_lat = np.radians(5.145) * np.sin(moon_F)
        moon_dist = 384400.0
        moon_x = moon_dist * np.cos(moon_lat) * np.cos(moon_lon)
        moon_y = moon_dist * np.cos(moon_lat) * np.sin(moon_lon)
        moon_z = moon_dist * np.sin(moon_lat)
        coords = np.column_stack([sun_x, sun_y, sun_z, moon_x, moon_y, moon_z])

    d_j2000_total = np.array([(t - J2000).total_seconds() / 86400.0 for t in times], dtype=np.float64)
    return {
        "times": times,
        "coords": coords,
        "d_j2000_total": d_j2000_total,
    }


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def get_lunar_body_matrix(d_j2000):
    omega = math.radians(125.04452 - 0.0529537648 * d_j2000)
    L = math.radians(218.3164477 + 13.17639648 * d_j2000)
    node_eq = omega + math.pi
    W = L - node_eq + math.pi
    return rot_z(-W) @ rot_x(-I_MOON) @ rot_z(-node_eq)


def get_earth_fixed_axes_ecliptic(d_j2000):
    """Osie ziemskiego układu stałego w ekliptyce J2000.

    Greenwich sidereal angle is anchored at J2000 (GMST = 280.46061837 deg).
    The Earth pole is tilted by the mean obliquity; this is a visual/astronomical
    approximation (UT1-UTC and small polar motion are not modelled).
    Returned vectors are X Greenwich, Y east, Z north, all unit length.
    """
    T = float(d_j2000) / 36525.0
    eps_arcsec = 84381.448 - 46.8150 * T - 0.00059 * T * T + 0.001813 * T * T * T
    eps = math.radians(eps_arcsec / 3600.0)
    theta = math.radians((280.46061837 + 360.98564736629 * float(d_j2000)) % 360.0)
    ct, st = math.cos(theta), math.sin(theta)
    ce, se = math.cos(eps), math.sin(eps)

    x_greenwich = np.array([ct, st * ce, st * se], dtype=np.float64)
    y_east = np.array([-st, ct * ce, ct * se], dtype=np.float64)
    z_north = np.array([0.0, -se, ce], dtype=np.float64)
    return x_greenwich, y_east, z_north


def get_topocentric_vectors(year_data, time_idx_float, lat_deg, lon_deg, obs_radius_km=R_MOON):
    """Topocentriczne położenia Słońca/Ziemi oraz wektory oświetlenia.

    Współrzędne z CSV są geocentryczne i ekliptyczne J2000:
    Earth->Sun oraz Earth->Moon. Macierz R_body przekształca ekliptykę J2000
    do księżycowego układu selenograficznego.
    """
    times = year_data["times"]
    coords = year_data["coords"]
    d_j2000_arr = year_data["d_j2000_total"]

    time_idx_float = float(np.clip(time_idx_float, 0.0, len(times) - 1.0))
    idx0 = int(math.floor(time_idx_float))
    idx1 = min(idx0 + 1, len(times) - 1)
    frac = time_idx_float - idx0

    d_j2000 = d_j2000_arr[idx0] * (1.0 - frac) + d_j2000_arr[idx1] * frac
    row_interp = coords[idx0] * (1.0 - frac) + coords[idx1] * frac

    sun_geo_ecl = row_interp[0:3]       # Earth -> Sun
    moon_geo_ecl = row_interp[3:6]      # Earth -> Moon

    earth_seleno_ecl = -moon_geo_ecl   # Moon -> Earth
    sun_seleno_ecl = sun_geo_ecl - moon_geo_ecl  # Moon -> Sun

    R_body = get_lunar_body_matrix(d_j2000)
    earth_body = R_body @ earth_seleno_ecl
    sun_body = R_body @ sun_seleno_ecl

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    up = np.array([
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    ], dtype=np.float64)
    east = np.array([-math.sin(lon), math.cos(lon), 0.0], dtype=np.float64)
    north = np.cross(up, east)

    obs_body = obs_radius_km * up
    vec_earth = earth_body - obs_body
    vec_sun = sun_body - obs_body

    def to_alt_az(v):
        dist = float(np.linalg.norm(v))
        if dist <= 0.0:
            raise ValueError("Zerowy wektor topocentryczny")
        alt = math.asin(float(np.clip(np.dot(v, up) / dist, -1.0, 1.0)))
        az = math.atan2(float(np.dot(v, east)), float(np.dot(v, north))) % (2.0 * math.pi)
        return alt, az, dist

    earth_alt, earth_az, earth_dist = to_alt_az(vec_earth)
    sun_alt, sun_az, sun_dist = to_alt_az(vec_sun)

    # Wektory potrzebne do narysowania globu Ziemi w tej samej przestrzeni
    # co wektory Horizons. earth_view_body wskazuje z Ziemi ku obserwatorowi
    # na Księżycu, sun_from_earth_body — z Ziemi ku Słońcu.
    earth_view_body = obs_body - earth_body
    earth_view_body /= np.linalg.norm(earth_view_body)
    sun_from_earth_body = sun_body - earth_body
    sun_from_earth_body /= np.linalg.norm(sun_from_earth_body)

    # Greenwich / biegun Ziemi obrócone do księżycowego układu współrzędnych.
    earth_axes_ecl = get_earth_fixed_axes_ecliptic(d_j2000)
    earth_axes_body = tuple(R_body @ axis for axis in earth_axes_ecl)

    current_time = times[idx0] + (times[idx1] - times[idx0]) * frac
    return {
        "time": current_time,
        "d_j2000": float(d_j2000),
        "R_body": R_body,
        "earth": (earth_alt, earth_az, earth_dist),
        "sun": (sun_alt, sun_az, sun_dist),
        "obs_bases": (north, east, up),
        "sun_earth_dir": sun_from_earth_body,
        "earth_view_body": earth_view_body,
        "earth_axes_body": earth_axes_body,
        "sun_body": sun_body,
        "earth_body": earth_body,
        "obs_body": obs_body,
    }


class Slider:
    def __init__(self, x, y, w, h, min_val, max_val, val, label, fmt="{:.2f}", is_int=False, power=1.0):
        self.rect = pygame.Rect(x, y, w, h)
        self.min_val, self.max_val, self.val = min_val, max_val, val
        self.label, self.fmt, self.is_int = label, fmt, is_int
        self.power = power
        self.dragging = False

    def _val_to_ratio(self):
        if self.max_val <= self.min_val:
            return 0.0
        norm = max(0.0, min(1.0, (self.val - self.min_val) / (self.max_val - self.min_val)))
        return norm ** (1.0 / self.power)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.inflate(10, 10).collidepoint(event.pos):
                self.dragging = True
                self.update_val(event.pos[0])
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.update_val(event.pos[0])
            return True
        return False

    def update_val(self, mx):
        ratio = max(0.0, min(1.0, (mx - self.rect.x) / self.rect.width))
        val = self.min_val + (ratio ** self.power) * (self.max_val - self.min_val)
        self.val = int(round(val)) if self.is_int else val

    def draw(self, screen, font, custom_text=None):
        pygame.draw.rect(screen, (60, 65, 75), self.rect, border_radius=4)
        ratio = self._val_to_ratio()
        fill_rect = pygame.Rect(self.rect.x, self.rect.y, int(self.rect.width * ratio), self.rect.height)
        pygame.draw.rect(screen, (100, 160, 230), fill_rect, border_radius=4)
        pygame.draw.circle(screen, (240, 245, 255), (self.rect.x + int(self.rect.width * ratio), self.rect.centery), 8)

        val_str = custom_text if custom_text else (str(int(self.val)) if self.is_int else self.fmt.format(self.val))
        txt = font.render(f"{self.label}: {val_str}", True, (230, 230, 230))
        screen.blit(txt, (self.rect.x, self.rect.y - 20))


def main():
    pygame.init()
    W, H = 1280, 800
    screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
    pygame.display.set_caption("Lunar Stellarium - NASA LOLA / LROC + ephemerydy J2000")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Consolas", 15)
    font_big = pygame.font.SysFont("Consolas", 18, bold=True)

    dem_km, albedo_rgb, dem_source = load_or_download_lunar_maps()
    terrain_3d = LunarTerrain3D(dem_km, albedo_rgb)
    wireframe_mode = False
    show_horizon_line = True

    earth_day_arr, earth_night_arr, earth_clouds_arr = load_earth_textures()

    cam_az = 0.0
    cam_alt = math.radians(15.0)
    base_fov = math.radians(75.0)
    fov = base_fov
    target_fov = base_fov
    MIN_FOV = math.radians(0.15)
    MAX_FOV = math.radians(115.0)

    dragging_sky = False
    last_mouse = (0, 0)
    playing = False
    play_speed = 24.0

    current_year = 2000
    year_data = load_year_data(current_year)

    slider_year = Slider(30, H - 45, 250, 10, 2000, 2100, current_year, "Rok", is_int=True)
    slider_time = Slider(300, H - 45, W - 330, 10, 0, len(year_data["times"]) - 1, 0, "Czas w roku")

    slider_lat = Slider(30, 40, 250, 10, -90.0, 90.0, -43.31, "Szerokość (Lat)", "{:+.2f}°")
    slider_lon = Slider(30, 90, 250, 10, -180.0, 180.0, -11.36, "Długość (Lon)", "{:+.2f}°")
    slider_alt = Slider(30, 140, 250, 10, 0.002, 200.0, 0.002, "Wysokość nad pow.", power=2.6)
    location_name = "Krater Tycho"

    np.random.seed(42)
    n_stars = 1200
    star_lam = np.random.uniform(0, 2 * np.pi, n_stars)
    star_beta = np.arcsin(np.random.uniform(-1, 1, n_stars))
    star_mags = np.random.randint(90, 255, n_stars)

    stars_ecl = np.stack([
        np.cos(star_beta) * np.cos(star_lam),
        np.cos(star_beta) * np.sin(star_lam),
        np.sin(star_beta),
    ], axis=-1)

    def zoom_at_point(zoom_factor, mx, my, cw, ch):
        nonlocal target_fov, cam_az, cam_alt
        old_target = target_fov
        target_fov = max(MIN_FOV, min(MAX_FOV, target_fov * zoom_factor))
        if abs(target_fov - old_target) < 1e-9:
            return
        focal_old = (ch / 2.0) / math.tan(old_target / 2.0)
        focal_new = (ch / 2.0) / math.tan(target_fov / 2.0)
        dx_px = mx - cw / 2.0
        dy_px = ch / 2.0 - my
        cam_az = (
            cam_az
            - (math.atan2(dx_px, focal_old) - math.atan2(dx_px, focal_new)) / max(0.25, math.cos(cam_alt))
        ) % (2.0 * math.pi)
        cam_alt = max(
            -math.pi / 2.0 + 0.01,
            min(math.pi / 2.0 - 0.01, cam_alt + (math.atan2(dy_px, focal_old) - math.atan2(dy_px, focal_new))),
        )

    def project_point(alt, az, cw, ch):
        px = math.cos(alt) * math.cos(az)
        py = math.cos(alt) * math.sin(az)
        pz = math.sin(alt)

        fwd = np.array([
            math.cos(cam_alt) * math.cos(cam_az),
            math.cos(cam_alt) * math.sin(cam_az),
            math.sin(cam_alt),
        ])
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(fwd, world_up)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([-math.sin(cam_az), math.cos(cam_az), 0.0])
        else:
            right /= np.linalg.norm(right)
        cam_up = np.cross(right, fwd)

        p = np.array([px, py, pz])
        z_cam = float(np.dot(p, fwd))
        if z_cam <= 0.05:
            return None

        x_cam = float(np.dot(p, right))
        y_cam = float(np.dot(p, cam_up))
        focal = float((ch / 2.0) / math.tan(fov / 2.0))
        return (
            float(cw / 2.0 + (x_cam / z_cam) * focal),
            float(ch / 2.0 - (y_cam / z_cam) * focal),
            z_cam,
            focal,
        )

    presets = {
        pygame.K_1: ("Krater Tycho", -43.31, -11.36),
        pygame.K_2: ("Krater Kopernik", 9.62, -20.08),
        pygame.K_3: ("Krater Shackleton (Biegun S)", -89.60, 0.00),
        pygame.K_4: ("Apollo 11 (Mare Tranquillitatis)", 0.67, 23.47),
        pygame.K_5: ("Mare Orientale", -19.40, -92.80),
    }

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        cw, ch = screen.get_size()

        slider_year.rect.y = ch - 45
        slider_time.rect.y = ch - 45
        slider_time.rect.width = max(200, cw - 330)

        old_year = current_year
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if slider_year.handle_event(event):
                current_year = int(slider_year.val)
            if slider_time.handle_event(event) or slider_alt.handle_event(event):
                continue
            if slider_lat.handle_event(event) or slider_lon.handle_event(event):
                location_name = "Własne współrzędne"
                continue

            if event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                factor = 0.80 ** event.y
                zoom_at_point(factor, mx, my, cw, ch)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    dragging_sky = True
                    last_mouse = event.pos
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    dragging_sky = False
            elif event.type == pygame.MOUSEMOTION and dragging_sky:
                dx, dy = event.pos[0] - last_mouse[0], event.pos[1] - last_mouse[1]
                last_mouse = event.pos
                sens = fov / ch
                cam_az = (cam_az - dx * sens) % (2 * math.pi)
                cam_alt = max(-math.pi / 2 + 0.01, min(math.pi / 2 - 0.01, cam_alt + dy * sens))
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    playing = not playing
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    zoom_at_point(0.75, cw / 2.0, ch / 2.0, cw, ch)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    zoom_at_point(1.0 / 0.75, cw / 2.0, ch / 2.0, cw, ch)
                elif event.key == pygame.K_r:
                    target_fov = base_fov
                elif event.key == pygame.K_e:
                    dist_ang = math.hypot(
                        cam_alt - data["earth"][0],
                        (cam_az - data["earth"][1] + math.pi) % (2 * math.pi) - math.pi,
                    )
                    cam_alt, cam_az = data["earth"][0], data["earth"][1]
                    if dist_ang < math.radians(3.0):
                        target_fov = math.radians(0.8) if target_fov <= math.radians(4.0) else math.radians(3.2)
                elif event.key == pygame.K_s:
                    dist_ang = math.hypot(
                        cam_alt - data["sun"][0],
                        (cam_az - data["sun"][1] + math.pi) % (2 * math.pi) - math.pi,
                    )
                    cam_alt, cam_az = data["sun"][0], data["sun"][1]
                    if dist_ang < math.radians(3.0):
                        target_fov = math.radians(0.45) if target_fov <= math.radians(2.0) else math.radians(1.4)
                elif event.key == pygame.K_l:
                    hor_alt = terrain_3d.get_horizon_at_azimuth(cam_az)
                    if abs(cam_alt - hor_alt) < math.radians(1.5):
                        target_fov = math.radians(8.0)
                    cam_alt = hor_alt
                elif event.key == pygame.K_m:
                    wireframe_mode = not wireframe_mode
                elif event.key == pygame.K_h:
                    show_horizon_line = not show_horizon_line
                elif event.key == pygame.K_c:
                    terrain_3d.update_observer(
                        slider_lat.val, slider_lon.val,
                        alt_above_surface_km=slider_alt.val,
                    )
                    if terrain_3d.horizon_alt is not None:
                        fname = "horizon.csv"
                        try:
                            with open(fname, "w", newline="", encoding="utf-8") as f_csv:
                                writer = csv.writer(f_csv)
                                writer.writerow(["Azimuth_deg", "Altitude_deg"])
                                for az_rad, alt_rad in zip(terrain_3d.az_grid[:-1], terrain_3d.horizon_alt):
                                    writer.writerow([f"{math.degrees(az_rad):.4f}", f"{math.degrees(alt_rad):.4f}"])
                            print(f"[OK] Zapisano horyzont topograficzny do: {fname}")
                        except Exception as e:
                            print(f"[BŁĄD] Nie udało się zapisać CSV: {e}")
                elif event.key in presets:
                    location_name, slider_lat.val, slider_lon.val = presets[event.key]

        fov += (target_fov - fov) * min(1.0, 14.0 * dt)

        if current_year != old_year:
            year_data = load_year_data(current_year)
            slider_time.max_val = len(year_data["times"]) - 1
            slider_time.val = min(slider_time.val, slider_time.max_val)

        if playing:
            slider_time.val += play_speed * dt
            if slider_time.val >= len(year_data["times"]) - 1:
                slider_time.val = 0

        terrain_3d.update_observer(slider_lat.val, slider_lon.val, alt_above_surface_km=slider_alt.val)

        data = get_topocentric_vectors(
            year_data,
            slider_time.val,
            slider_lat.val,
            slider_lon.val,
            obs_radius_km=terrain_3d.obs_radius_km,
        )
        earth_alt, earth_az, earth_dist = data["earth"]
        sun_alt, sun_az, sun_dist = data["sun"]
        north, east, up = data["obs_bases"]
        R_body = data["R_body"]
        sun_earth_dir = data["sun_earth_dir"]
        d_j2000 = data["d_j2000"]

        screen.fill((5, 7, 12))

        # 1. Gwiazdy
        stars_body = (R_body @ stars_ecl.T).T
        s_n = stars_body @ north
        s_e = stars_body @ east
        s_u = stars_body @ up

        star_alts = np.arcsin(np.clip(s_u, -1.0, 1.0))
        star_azs = np.arctan2(s_e, s_n) % (2 * np.pi)

        for s_alt, s_az, mag in zip(star_alts, star_azs, star_mags):
            if s_alt > -0.45:
                proj = project_point(float(s_alt), float(s_az), cw, ch)
                if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                    screen.set_at((int(proj[0]), int(proj[1])), (int(mag), int(mag), int(mag)))

        # 2. Siatka azymutalna
        grid_color = (25, 35, 50)
        for a_deg in range(0, 90, 30):
            a_rad = math.radians(a_deg)
            pts = [project_point(a_rad, math.radians(z), cw, ch) for z in range(0, 365, 5)]
            pts_xy = [(p[0], p[1]) if p else None for p in pts]
            for i in range(len(pts_xy) - 1):
                if pts_xy[i] and pts_xy[i + 1]:
                    pygame.draw.line(screen, grid_color, pts_xy[i], pts_xy[i + 1], 1)

        # 3. SŁOŃCE
        sun_proj = project_point(sun_alt, sun_az, cw, ch)
        if sun_proj:
            sx, sy, z_cam, focal = sun_proj
            r_sun_exact = math.asin(min(1.0, R_SUN / sun_dist)) * focal / z_cam
            draw_telescopic_sun(screen, sx, sy, r_sun_exact, cw, ch)
            r_label = max(4, int(r_sun_exact))
            if 0 <= sx + r_label + 6 < cw and 0 <= sy - 8 < ch:
                screen.blit(font.render("Słońce", True, (255, 230, 150)), (int(sx + r_label + 6), int(sy - 8)))

        # 4. ZIEMIA
        earth_proj = project_point(earth_alt, earth_az, cw, ch)
        if earth_proj:
            ex, ey, z_cam, focal = earth_proj
            r_earth_exact = math.asin(min(1.0, R_EARTH / earth_dist)) * focal / z_cam
            north, east, up = data["obs_bases"]
            _, camera_right_enu, camera_up_enu = get_camera_basis(cam_alt, cam_az)
            camera_right_body = (
                north * camera_right_enu[0]
                + east * camera_right_enu[1]
                + up * camera_right_enu[2]
            )
            camera_up_body = (
                north * camera_up_enu[0]
                + east * camera_up_enu[1]
                + up * camera_up_enu[2]
            )
            draw_telescopic_earth(
                screen, ex, ey, r_earth_exact, cw, ch,
                data["earth_view_body"], camera_right_body, camera_up_body,
                sun_earth_dir, data["earth_axes_body"],
                day_arr=earth_day_arr,
                night_arr=earth_night_arr,
                clouds_arr=earth_clouds_arr,
            )
            r_elabel = max(6, int(r_earth_exact))
            if 0 <= ex + r_elabel + 8 < cw and 0 <= ey - 8 < ch:
                screen.blit(font.render("Ziemia", True, (130, 200, 255)), (int(ex + r_elabel + 8), int(ey - 8)))

        # 5. PIKSELOWY SHADER POWIERZCHNI KSIĘŻYCA
        terrain_3d.draw_3d(
            screen, cw, ch, cam_alt, cam_az, fov,
            sun_alt, sun_az, earth_alt,
            wireframe=wireframe_mode,
            show_horizon_line=show_horizon_line,
        )

        # 6. Kierunki świata nad lokalnym horyzontem topograficznym
        for label, deg in [("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315)]:
            az_r = math.radians(deg)
            h_alt = terrain_3d.get_horizon_at_azimuth(az_r) + max(math.radians(1.2), fov * 0.02)
            proj = project_point(h_alt, az_r, cw, ch)
            if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                col = (255, 90, 90) if label == "N" else (210, 220, 235)
                txt = font_big.render(label, True, col)
                screen.blit(txt, (int(proj[0] - txt.get_width() // 2), int(proj[1] - txt.get_height() // 2)))

        # 7. HUD
        earth_hor = terrain_3d.get_horizon_at_azimuth(earth_az)
        sun_hor = terrain_3d.get_horizon_at_azimuth(sun_az)
        cam_hor = terrain_3d.get_horizon_at_azimuth(cam_az)
        zoom_mag = base_fov / fov

        earth_vis = "WIDOCZNA" if earth_alt > earth_hor else "ZA HORYZONTEM"
        sun_vis = "WIDOCZNE" if sun_alt > sun_hor else "ZA HORYZONTEM"
        alt_text = f"{slider_alt.val * 1000.0:.1f} m" if slider_alt.val < 1.0 else f"{slider_alt.val:.2f} km"

        info_lines = [
            f"Lokacja: {location_name} | DEM: {dem_source} | FPS: {clock.get_fps():.0f}",
            f"Grunt: {terrain_3d.obs_elev_km:+.3f} km | Wys. nad pow.: {alt_text} | Zoom: {zoom_mag:.1f}x",
            f"Kamera: Az {math.degrees(cam_az):.2f}° | Alt {math.degrees(cam_alt):+.2f}° (Hor: {math.degrees(cam_hor):+.2f}°)",
            "-" * 60,
            f"ZIEMIA: Alt {math.degrees(earth_alt):+6.2f}° | Az {math.degrees(earth_az):6.2f}° [{earth_vis}]",
            f"SŁOŃCE: Alt {math.degrees(sun_alt):+6.2f}° | Az {math.degrees(sun_az):6.2f}° [{sun_vis}]",
            "-" * 60,
            "[Scroll / +/-] Zoom (do 500x) | [R] Reset zoomu | [Spacja] Play",
            "[E] Ziemia (2x = zoom) | [S] Słońce (2x = zoom) | [L] Horyzont",
            "[C] Zapisz horyzont (CSV) | [M] Siatka 3D | [H] Horyzont | [1-5] Lokacje",
        ]

        panel_w = 620
        panel_surf = pygame.Surface((panel_w, len(info_lines) * 20 + 16), pygame.SRCALPHA)
        panel_surf.fill((15, 20, 30, 195))
        screen.blit(panel_surf, (cw - panel_w - 15, 15))

        for i, line in enumerate(info_lines):
            screen.blit(font.render(line, True, (210, 215, 225)), (cw - panel_w - 5, 22 + i * 20))

        slider_year.draw(screen, font)
        slider_time.draw(screen, font, data["time"].strftime("%Y-%m-%d %H:%M UTC"))
        slider_lat.draw(screen, font)
        slider_lon.draw(screen, font)
        slider_alt.draw(screen, font, alt_text)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()


