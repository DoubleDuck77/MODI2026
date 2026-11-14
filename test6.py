import os
import sys
import csv
import math
import urllib.request
from datetime import datetime, timedelta
import numpy as np
import pygame

# --- STAŁE ASTRONOMICZNE ---
R_MOON = 1737.4   # Średni promień Księżyca w km
R_EARTH = 6371.0  # Promień Ziemi w km
R_SUN = 696340.0  # Promień Słońca w km

EPS_J2000 = math.radians(23.43929111111111)  # Nachylenie ekliptyki J2000.0 (IAU 2000/2006)
SIDEREAL_MONTH = 27.321661                   # dni
J2000 = datetime(2000, 1, 1, 12, 0, 0)

# Globalny zakres wysokości mapy NASA LRO LOLA DEM (w km względem R_MOON)
LOLA_MIN_KM = -9.12
LOLA_MAX_KM = 10.76

# Stabilne linki do oficjalnych map NASA (SVS Moon CGI Kit)
LOLA_DEM_URLS = [
    "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/ldem_3_8bit.jpg",
]

LRO_COLOR_URLS = [
    "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_1k.jpg",
]

EARTH_DAY_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/Blue_Marble_2002.png/1280px-Blue_Marble_2002.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Equirectangular_projection_SW.jpg/1280px-Equirectangular_projection_SW.jpg",
]

EARTH_NIGHT_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/ba/The_earth_at_night.jpg/1280px-The_earth_at_night.jpg",
]


def _download_first_available(urls, dest_path, label):
    if os.path.exists(dest_path):
        return True
    for url in urls:
        try:
            print(f"[POBIERANIE] {label}: {url} ...")
            req = urllib.request.Request(url, headers={"User-Agent": "LunarStellarium/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp, open(dest_path, "wb") as out:
                out.write(resp.read())
            print(f"[OK] Zapisano: {dest_path}")
            return True
        except Exception as e:
            print(f"[OSTRZEŻENIE] Nie udało się pobrać {label} z {url}: {e}")
    return False


def generate_fallback_lunar_dem(H=720, W=1440):
    """Generuje zapasową mapę wysokości Księżyca (w km), gdy brak dostępu do sieci."""
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
    """Tworzy realistyczną mapę tekstury albedo Księżyca (morza bazaltowe, wyżyny, promienie kraterów)."""
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
    """Wczytuje lub pobiera globalną mapę wysokości (DEM) oraz mapę tekstury albedo Księżyca."""
    os.makedirs("Textures", exist_ok=True)
    dem_cache = os.path.join("Textures", "moon_dem.npy")
    dem_img = os.path.join("Textures", "moon_dem.jpg")
    alb_cache = os.path.join("Textures", "moon_albedo.npy")
    alb_img = os.path.join("Textures", "moon_color.jpg")

    if os.path.exists(dem_cache):
        dem = np.load(dem_cache)
        dem_src = "LOLA DEM (cache)"
    else:
        _download_first_available(LOLA_DEM_URLS, dem_img, "Mapa wysokości NASA LOLA DEM")
        if os.path.exists(dem_img):
            try:
                surf = pygame.image.load(dem_img)
                arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)
                gray = arr[:, :, 0].astype(np.float32)
                dem = LOLA_MIN_KM + (gray / 255.0) * (LOLA_MAX_KM - LOLA_MIN_KM)
                np.save(dem_cache, dem)
                dem_src = "NASA LRO LOLA DEM"
            except Exception:
                dem = generate_fallback_lunar_dem()
                dem_src = "Proceduralny DEM"
        else:
            dem = generate_fallback_lunar_dem()
            dem_src = "Proceduralny DEM"

    if os.path.exists(alb_cache):
        albedo_rgb = np.load(alb_cache)
    else:
        custom_tex = next(
            (p for p in ["Textures/moon_color8K.jpg", "Textures/moon_color.jpg", "Textures/moon_albedo.jpg"] if os.path.exists(p)),
            None,
        )
        if custom_tex is None and _download_first_available(LRO_COLOR_URLS[:1], alb_img, "Tekstura powierzchni NASA LRO WAC"):
            custom_tex = alb_img

        if custom_tex is not None:
            try:
                surf = pygame.image.load(custom_tex)
                arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2).astype(np.float32) / 255.0
                albedo_rgb = 0.055 + 0.22 * np.power(arr, 1.15)
                np.save(alb_cache, albedo_rgb.astype(np.float32))
                print(f"[OK] Przetworzono teksturę powierzchni Księżyca: {custom_tex}")
            except Exception:
                albedo_rgb = generate_fallback_lunar_albedo(dem)
        else:
            albedo_rgb = generate_fallback_lunar_albedo(dem)

    return dem, albedo_rgb, dem_src


def build_night_mipmaps(night_arr: np.ndarray):
    """Buduje piramidę mipmap zachowującą jasność punktów świetlnych miast przy oddaleniu."""
    if night_arr is None:
        return None
    mips = [night_arr]
    cur = night_arr
    while cur.shape[0] >= 256 and cur.shape[1] >= 512:
        h = (cur.shape[0] // 2) * 2
        w = (cur.shape[1] // 2) * 2
        cropped = cur[:h, :w].astype(np.float32)
        blocks = cropped.reshape(h // 2, 2, w // 2, 2, 3)
        b_mean = blocks.mean(axis=(1, 3))
        b_max = blocks.max(axis=(1, 3))
        cur = np.clip(0.45 * b_mean + 0.55 * b_max, 0, 255).astype(np.uint8)
        mips.append(cur)
    return mips


def load_earth_textures():
    """Wczytuje tekstury Ziemi (dzień, noc, chmury) z folderu Textures/."""
    os.makedirs("Textures", exist_ok=True)
    valid_exts = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")

    def _find_local_texture(exact_candidates, keyword):
        for p in exact_candidates:
            if os.path.exists(p):
                return p
        if os.path.isdir("Textures"):
            matches = [
                fn for fn in os.listdir("Textures")
                if keyword in fn.lower() and "earth" in fn.lower() and fn.lower().endswith(valid_exts)
            ]
            if matches:
                matches.sort(key=lambda fn: (0 if "8k" in fn.lower() else 1, len(fn)))
                return os.path.join("Textures", matches[0])
        return None

    day_path = _find_local_texture(
        ["Textures/earth_day8K.jpg", "Textures/earth_day8K.png", "Textures/earth_day.jpg", "Textures/earth_day.png"],
        "day",
    )
    if day_path is None:
        dl_path = "Textures/earth_day.jpg"
        if _download_first_available(EARTH_DAY_URLS, dl_path, "Tekstura Ziemi (Blue Marble)"):
            day_path = dl_path

    night_path = _find_local_texture(
        ["Textures/earth_night8K.jpg", "Textures/earth_night8K.png", "Textures/earth_night.jpg", "Textures/earth_night.png"],
        "night",
    )
    if night_path is None:
        dl_night = "Textures/earth_night.jpg"
        if _download_first_available(EARTH_NIGHT_URLS, dl_night, "Tekstura Ziemi nocą (światła miast)"):
            night_path = dl_night

    clouds_path = _find_local_texture(
        ["Textures/earth_clouds8K.jpg", "Textures/earth_clouds8K.png", "Textures/earth_clouds.jpg", "Textures/earth_clouds.png"],
        "cloud",
    )

    def _to_rgb_array(path, label):
        if not path:
            print(f"[OSTRZEŻENIE] Brak tekstury {label} w folderze Textures/")
            return None
        try:
            surf = pygame.image.load(path).convert()
            print(f"[OK] Wczytano teksturę {label}: {path} ({surf.get_width()}x{surf.get_height()})")
            return pygame.surfarray.array3d(surf).transpose(1, 0, 2)
        except Exception as e:
            print(f"[OSTRZEŻENIE] Błąd wczytywania {path}: {e}")
            return None

    day_arr = _to_rgb_array(day_path, "dziennej Ziemi")
    night_arr = _to_rgb_array(night_path, "nocnej Ziemi (światła miast)")
    clouds_arr = _to_rgb_array(clouds_path, "chmur Ziemi")
    night_mips = build_night_mipmaps(night_arr)
    return day_arr, night_mips, clouds_arr


def circle_overlap_fraction(r_target: float, r_occulter: float, dist: float) -> float:
    """Zwraca ułamek pola koła r_target zasłonięty przez koło r_occulter w odległości kątowej dist."""
    if dist >= r_target + r_occulter or r_target <= 0.0:
        return 0.0
    if dist <= abs(r_occulter - r_target):
        if r_occulter >= r_target:
            return 1.0
        return (r_occulter / r_target) ** 2

    r1, r2, d = r_target, r_occulter, dist
    cos1 = max(-1.0, min(1.0, (d * d + r1 * r1 - r2 * r2) / (2.0 * d * r1)))
    cos2 = max(-1.0, min(1.0, (d * d + r2 * r2 - r1 * r1) / (2.0 * d * r2)))
    part1 = r1 * r1 * math.acos(cos1)
    part2 = r2 * r2 * math.acos(cos2)
    part3 = 0.5 * math.sqrt(max(0.0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    area_overlap = part1 + part2 - part3
    return max(0.0, min(1.0, area_overlap / (math.pi * r1 * r1)))


def horizon_visible_fraction(sun_alt: float, hor_alt: float, r_sun: float) -> float:
    """Zwraca ułamek tarczy Słońca o promieniu r_sun leżący ponad lokalnym horyzontem hor_alt."""
    if r_sun <= 0.0:
        return 1.0 if sun_alt > hor_alt else 0.0
    x = (sun_alt - hor_alt) / r_sun
    if x <= -1.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return 0.5 + (x * math.sqrt(max(0.0, 1.0 - x * x)) + math.asin(x)) / math.pi


def _clip_poly_near(verts, near_z: float):
    """Przycina wielokąt 3D w układzie kamery [(x, y, z), ...] do płaszczyzny z >= near_z."""
    out = []
    n = len(verts)
    for idx in range(n):
        x1, y1, z1 = verts[idx]
        x2, y2, z2 = verts[(idx + 1) % n]
        in1 = z1 >= near_z
        in2 = z2 >= near_z
        if in1 and in2:
            out.append((x2, y2, z2))
        elif in1 and not in2:
            t = (near_z - z1) / (z2 - z1)
            out.append((x1 + t * (x2 - x1), y1 + t * (y2 - y1), near_z))
        elif not in1 and in2:
            t = (near_z - z1) / (z2 - z1)
            out.append((x1 + t * (x2 - x1), y1 + t * (y2 - y1), near_z))
            out.append((x2, y2, z2))
    return out


class LunarTerrain3D:
    """
    Model 3D powierzchni Księżyca oparty na regularnej siatce kartezjańskiej (North, East)
    odwzorowanej na kulistą powierzchnię Księżyca (bez osobliwości biegunowej pod obserwatorem)
    oraz niezależnym raycastingu 360° profilu horyzontu topograficznego.
    """

    def __init__(self, dem_km: np.ndarray, albedo_rgb: np.ndarray):
        self.dem = dem_km
        self.H, self.W = dem_km.shape
        self.albedo_map = albedo_rgb
        self.AH, self.AW = albedo_rgb.shape[:2]

        # Kartezjańska oś współrzędnych stycznych (North, East) w km:
        # drobne prostokątne kafelki przy obserwatorze (~2.5 m), płynnie rozszerzające się do ±450 km.
        self.n_half = 75
        t = np.linspace(0.0, 1.0, self.n_half + 1)
        min_step_km = 0.0025
        half_span_km = 450.0
        pos = min_step_km * self.n_half * t + (half_span_km - min_step_km * self.n_half) * (t ** 4.2)
        self.axis_km = np.concatenate((-pos[:0:-1], pos))
        self.n_pts = len(self.axis_km)
        self.n_cells = self.n_pts - 1

        N_grid, E_grid = np.meshgrid(self.axis_km, self.axis_km, indexing="ij")
        self.N_grid = N_grid
        self.E_grid = E_grid
        self.s_grid = np.hypot(N_grid, E_grid)
        self.delta_grid = self.s_grid / R_MOON
        self.sinc_over_R = np.where(
            self.s_grid > 1e-12,
            np.sin(self.delta_grid) / np.maximum(self.s_grid, 1e-12),
            1.0 / R_MOON,
        )
        self.cos_delta_grid = np.cos(self.delta_grid)

        # Niezależna siatka biegunowa wyłącznie do dokładnego wyznaczania profilu horyzontu 360°
        self.hor_radii_km = np.geomspace(0.02, 450.0, 120)
        self.az_grid = np.linspace(0.0, 2.0 * np.pi, 721)
        self.n_az = len(self.az_grid) - 1

        self.cached_lat = None
        self.cached_lon = None
        self.cached_eye_height_m = None
        self.pts_enu = None
        self.normals_enu = None
        self.quad_rgb = None
        self.horizon_alt = None
        self.horizon_dist_km = None
        self.horizon_lat = None
        self.horizon_lon = None
        self.horizon_elev_km = None
        self.obs_elev_km = 0.0
        self.obs_radius_km = R_MOON

    def sample_dem_bilinear(self, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
        fy = np.clip((90.0 - lat_deg) / 180.0 * (self.H - 1), 0.0, self.H - 1.0001)
        lon_wrapped = ((lon_deg + 180.0) % 360.0) - 180.0
        fx = (lon_wrapped + 180.0) / 360.0 * self.W

        y0 = np.floor(fy).astype(np.int32)
        x0 = np.floor(fx).astype(np.int32) % self.W
        y1 = np.minimum(y0 + 1, self.H - 1)
        x1 = (x0 + 1) % self.W

        wy = fy - y0
        wx = fx - np.floor(fx)

        base_h = (
            (self.dem[y0, x0] * (1.0 - wx) + self.dem[y0, x1] * wx) * (1.0 - wy)
            + (self.dem[y1, x0] * (1.0 - wx) + self.dem[y1, x1] * wx) * wy
        )

        lat_r = np.radians(lat_deg)
        lon_r = np.radians(lon_wrapped)
        detail = (
            0.032 * np.sin(lat_r * 950.0) * np.cos(lon_r * 950.0)
            + 0.014 * np.sin(lat_r * 2600.0 + 1.1) * np.sin(lon_r * 2600.0 - 0.7)
            + 0.005 * np.cos(lat_r * 7200.0 - lon_r * 6400.0)
        )
        return base_h + detail

    def sample_surface_texture(self, lat_deg: np.ndarray, lon_deg: np.ndarray, rel_n: np.ndarray, rel_e: np.ndarray) -> np.ndarray:
        """Próbkuje teksturę globalną Księżyca + wieloskalową fakturę regolitu i skał."""
        fy = np.clip((90.0 - lat_deg) / 180.0 * (self.AH - 1), 0.0, self.AH - 1.0001)
        lon_wrapped = ((lon_deg + 180.0) % 360.0) - 180.0
        fx = (lon_wrapped + 180.0) / 360.0 * self.AW

        y0 = np.floor(fy).astype(np.int32)
        x0 = np.floor(fx).astype(np.int32) % self.AW
        y1 = np.minimum(y0 + 1, self.AH - 1)
        x1 = (x0 + 1) % self.AW

        wy = (fy - y0)[..., None]
        wx = (fx - np.floor(fx))[..., None]

        base_rgb = (
            (self.albedo_map[y0, x0] * (1.0 - wx) + self.albedo_map[y0, x1] * wx) * (1.0 - wy)
            + (self.albedo_map[y1, x0] * (1.0 - wx) + self.albedo_map[y1, x1] * wx) * wy
        )

        lat_r = np.radians(lat_deg)
        lon_r = np.radians(lon_wrapped)
        macro_tex = (
            0.12 * np.sin(lat_r * 520.0 + 0.4) * np.cos(lon_r * 520.0 - 0.6)
            + 0.09 * np.cos(lat_r * 1650.0 - lon_r * 1420.0)
        )
        micro_tex = (
            0.14 * np.sin(rel_n * 42.0 + rel_e * 31.0) * np.cos(rel_n * 24.0 - rel_e * 49.0)
            + 0.10 * np.sin(rel_n * 130.0 - rel_e * 112.0)
            + 0.07 * np.cos(rel_n * 310.0 + rel_e * 275.0)
        )
        dist_km = np.hypot(rel_n, rel_e)
        micro_weight = np.exp(-dist_km / 3.0)

        tex_factor = np.clip(1.0 + macro_tex + micro_tex * micro_weight, 0.50, 1.55)
        return base_rgb * tex_factor[..., None]

    def update_observer(self, lat_deg: float, lon_deg: float, eye_height_m: float = 2.0):
        if (
            self.cached_lat == lat_deg
            and self.cached_lon == lon_deg
            and self.cached_eye_height_m == eye_height_m
        ):
            return
        self.cached_lat = lat_deg
        self.cached_lon = lon_deg
        self.cached_eye_height_m = eye_height_m

        ground_h = float(self.sample_dem_bilinear(np.array([lat_deg]), np.array([lon_deg]))[0])
        self.obs_elev_km = ground_h
        self.obs_radius_km = R_MOON + ground_h + (eye_height_m / 1000.0)

        lat0 = math.radians(lat_deg)
        lon0 = math.radians(lon_deg)
        up0 = np.array([math.cos(lat0) * math.cos(lon0), math.cos(lat0) * math.sin(lon0), math.sin(lat0)])
        east0 = np.array([-math.sin(lon0), math.cos(lon0), 0.0])
        north0 = np.cross(up0, east0)
        obs_body = self.obs_radius_km * up0

        # 1. Kartezjańska siatka prostokątna (North, East) odwzorowana na sferę Księżyca
        u_body = (
            self.cos_delta_grid[..., None] * up0[None, None, :]
            + (self.N_grid * self.sinc_over_R)[..., None] * north0[None, None, :]
            + (self.E_grid * self.sinc_over_R)[..., None] * east0[None, None, :]
        )

        v_lat = np.degrees(np.arcsin(np.clip(u_body[..., 2], -1.0, 1.0)))
        v_lon = np.degrees(np.arctan2(u_body[..., 1], u_body[..., 0]))

        h_grid = self.sample_dem_bilinear(v_lat, v_lon)
        r_grid = R_MOON + h_grid

        p_body = r_grid[..., None] * u_body
        rel_body = p_body - obs_body[None, None, :]

        rel_n = rel_body @ north0
        rel_e = rel_body @ east0
        rel_u = rel_body @ up0
        self.pts_enu = np.stack([rel_n, rel_e, rel_u], axis=-1)

        # Normalne powierzchni dla kafelków prostokątnych (i, j) -> (i+1, j), (i+1, j+1), (i, j+1)
        p00 = self.pts_enu[:-1, :-1]
        p10 = self.pts_enu[1:, :-1]
        p11 = self.pts_enu[1:, 1:]
        p01 = self.pts_enu[:-1, 1:]

        # Diag1 = p11 - p00, Diag2 = p01 - p10 -> krzyż daje wektor skierowany w górę (+Up)
        normals = np.cross(p11 - p00, p01 - p10)
        norms = np.linalg.norm(normals, axis=-1, keepdims=True)
        normals = normals / np.maximum(norms, 1e-15)

        # Wzmocnienie kontrastu rzeźby terenu (ściany kraterów, grzbiety) na składowych poziomych normalnej
        relief_gain = 1.85
        normals[..., 0] *= relief_gain
        normals[..., 1] *= relief_gain

        mid_n = 0.25 * (rel_n[:-1, :-1] + rel_n[1:, :-1] + rel_n[1:, 1:] + rel_n[:-1, 1:])
        mid_e = 0.25 * (rel_e[:-1, :-1] + rel_e[1:, :-1] + rel_e[1:, 1:] + rel_e[:-1, 1:])
        mid_lat = 0.25 * (v_lat[:-1, :-1] + v_lat[1:, :-1] + v_lat[1:, 1:] + v_lat[:-1, 1:])
        mid_lon = 0.25 * (v_lon[:-1, :-1] + v_lon[1:, :-1] + v_lon[1:, 1:] + v_lon[:-1, 1:])

        bump_n = 0.045 * np.sin(mid_n * 55.0 - mid_e * 37.0)
        bump_e = 0.045 * np.cos(mid_n * 43.0 + mid_e * 61.0)
        normals[..., 0] += bump_n
        normals[..., 1] += bump_e
        normals /= np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-15)
        self.normals_enu = normals

        self.quad_rgb = self.sample_surface_texture(mid_lat, mid_lon, mid_n, mid_e)

        # 2. Niezależny profil horyzontu topograficznego 360° (720 azymutów x 120 promieni do 450 km)
        delta_h = (self.hor_radii_km / R_MOON)[:, None]
        az_h = self.az_grid[None, :]
        u_hor = (
            np.cos(delta_h)[..., None] * up0[None, None, :]
            + (np.sin(delta_h) * np.cos(az_h))[..., None] * north0[None, None, :]
            + (np.sin(delta_h) * np.sin(az_h))[..., None] * east0[None, None, :]
        )
        h_lat = np.degrees(np.arcsin(np.clip(u_hor[..., 2], -1.0, 1.0)))
        h_lon = np.degrees(np.arctan2(u_hor[..., 1], u_hor[..., 0]))
        h_elev = self.sample_dem_bilinear(h_lat, h_lon)
        r_hor = R_MOON + h_elev

        rel_hor = r_hor[..., None] * u_hor - obs_body[None, None, :]
        dist_hor = np.linalg.norm(rel_hor, axis=-1)
        rel_u_hor = rel_hor @ up0
        elev_angles = np.arcsin(np.clip(rel_u_hor / np.maximum(dist_hor, 1e-9), -1.0, 1.0))

        hor_idx = np.argmax(elev_angles, axis=0)
        az_indices = np.arange(elev_angles.shape[1])

        self.horizon_alt = elev_angles[hor_idx, az_indices]
        self.horizon_dist_km = dist_hor[hor_idx, az_indices]
        self.horizon_lat = h_lat[hor_idx, az_indices]
        self.horizon_lon = h_lon[hor_idx, az_indices]
        self.horizon_elev_km = h_elev[hor_idx, az_indices]

    def get_horizon_at_azimuth(self, az_rad: float) -> float:
        return float(np.interp(az_rad % (2.0 * np.pi), self.az_grid, self.horizon_alt))

    def export_horizon_csv(self, filename="horizon.csv"):
        """Zapisuje profil horyzontu geograficznego dla wszystkich azymutów do pliku CSV."""
        with open(filename, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Azimuth_deg",
                "Horizon_Altitude_deg",
                "Horizon_Distance_km",
                "Horizon_Lat_deg",
                "Horizon_Lon_deg",
                "Horizon_Elevation_km",
                "Observer_Lat_deg",
                "Observer_Lon_deg",
                "Observer_Elevation_km",
                "Observer_Height_above_surface_m",
            ])
            for idx in range(self.n_az):
                writer.writerow([
                    f"{math.degrees(self.az_grid[idx]):.4f}",
                    f"{math.degrees(self.horizon_alt[idx]):.6f}",
                    f"{float(self.horizon_dist_km[idx]):.4f}",
                    f"{float(self.horizon_lat[idx]):.6f}",
                    f"{float(self.horizon_lon[idx]):.6f}",
                    f"{float(self.horizon_elev_km[idx]):.5f}",
                    f"{self.cached_lat:.6f}",
                    f"{self.cached_lon:.6f}",
                    f"{self.obs_elev_km:.5f}",
                    f"{self.cached_eye_height_m:.2f}",
                ])
        print(f"[OK] Wyeksportowano dane horyzontu do: {filename}")

    def draw_3d(self, screen, cw, ch, cam_alt, cam_az, fov, sun_alt, sun_az, earth_alt,
                sun_effective_vis=1.0, eclipse_red_glow=0.0,
                wireframe=False, show_horizon_line=True):
        # Prawoskrętna baza kamery w układzie [North, East, Up]
        fwd = np.array([
            math.cos(cam_alt) * math.cos(cam_az),
            math.cos(cam_alt) * math.sin(cam_az),
            math.sin(cam_alt),
        ])
        right = np.array([-math.sin(cam_az), math.cos(cam_az), 0.0])
        cam_up = np.array([
            -math.sin(cam_alt) * math.cos(cam_az),
            -math.sin(cam_alt) * math.sin(cam_az),
            math.cos(cam_alt),
        ])

        z_cam = self.pts_enu @ fwd
        x_cam = self.pts_enu @ right
        y_cam = self.pts_enu @ cam_up

        near_z = 0.0002
        focal = (ch / 2.0) / math.tan(fov / 2.0)
        safe_z = np.where(z_cam > near_z, z_cam, near_z)
        sx = cw / 2.0 + (x_cam / safe_z) * focal
        sy = ch / 2.0 - (y_cam / safe_z) * focal

        sun_enu = np.array([
            math.cos(sun_alt) * math.cos(sun_az),
            math.cos(sun_alt) * math.sin(sun_az),
            math.sin(sun_alt),
        ])
        ndotl = np.einsum("ijk,k->ij", self.normals_enu, sun_enu)
        direct = np.power(np.maximum(0.0, ndotl), 0.85) * sun_effective_vis
        earthshine = 0.045 * max(0.0, math.sin(earth_alt))
        ambient = 0.032 + earthshine

        base_light = 165.0 * ambient + 940.0 * direct
        red_tint = 1.0 + 0.85 * eclipse_red_glow
        green_tint = 1.0 - 0.15 * eclipse_red_glow
        blue_tint = 1.0 - 0.35 * eclipse_red_glow

        lit_rgb = np.empty(self.quad_rgb.shape, dtype=np.uint8)
        lit_rgb[..., 0] = np.clip(self.quad_rgb[..., 0] * base_light * red_tint, 5, 248)
        lit_rgb[..., 1] = np.clip(self.quad_rgb[..., 1] * base_light * green_tint, 5, 248)
        lit_rgb[..., 2] = np.clip(self.quad_rgb[..., 2] * base_light * blue_tint, 5, 248)

        # Sortowanie malarskie od zewnętrznych krawędzi siatki kartezjańskiej ku środkowi (obserwatorowi)
        mid = self.n_half
        i_order = list(range(0, mid)) + list(range(self.n_cells - 1, mid - 1, -1))
        j_order = list(range(0, mid)) + list(range(self.n_cells - 1, mid - 1, -1))

        half_cw = cw / 2.0
        half_ch = ch / 2.0
        margin = 90.0

        for i in i_order:
            z00_row = z_cam[i, :-1]
            z10_row = z_cam[i + 1, :-1]
            z11_row = z_cam[i + 1, 1:]
            z01_row = z_cam[i, 1:]

            any_in_front = (z00_row > near_z) | (z10_row > near_z) | (z11_row > near_z) | (z01_row > near_z)
            if not np.any(any_in_front):
                continue

            x00_r, y00_r = sx[i, :-1], sy[i, :-1]
            x10_r, y10_r = sx[i + 1, :-1], sy[i + 1, :-1]
            x11_r, y11_r = sx[i + 1, 1:], sy[i + 1, 1:]
            x01_r, y01_r = sx[i, 1:], sy[i, 1:]
            row_col = lit_rgb[i]

            for j in j_order:
                if not any_in_front[j]:
                    continue

                z00, z10, z11, z01 = z00_row[j], z10_row[j], z11_row[j], z01_row[j]
                if z00 > near_z and z10 > near_z and z11 > near_z and z01 > near_z:
                    px00, py00 = x00_r[j], y00_r[j]
                    px10, py10 = x10_r[j], y10_r[j]
                    px11, py11 = x11_r[j], y11_r[j]
                    px01, py01 = x01_r[j], y01_r[j]

                    if (
                        max(px00, px10, px11, px01) < -margin
                        or min(px00, px10, px11, px01) > cw + margin
                        or max(py00, py10, py11, py01) < -margin
                        or min(py00, py10, py11, py01) > ch + margin
                    ):
                        continue

                    poly = [
                        (int(px00), int(py00)),
                        (int(px10), int(py10)),
                        (int(px11), int(py11)),
                        (int(px01), int(py01)),
                    ]
                else:
                    # Przycięcie kafelka przecinającego bliską płaszczyznę kamery (brak dziury u dołu ekranu!)
                    clipped = _clip_poly_near(
                        [
                            (float(x_cam[i, j]), float(y_cam[i, j]), float(z00)),
                            (float(x_cam[i + 1, j]), float(y_cam[i + 1, j]), float(z10)),
                            (float(x_cam[i + 1, j + 1]), float(y_cam[i + 1, j + 1]), float(z11)),
                            (float(x_cam[i, j + 1]), float(y_cam[i, j + 1]), float(z01)),
                        ],
                        near_z,
                    )
                    if len(clipped) < 3:
                        continue
                    poly = [
                        (
                            int(max(-16000.0, min(16000.0, half_cw + (vx / vz) * focal))),
                            int(max(-16000.0, min(16000.0, half_ch - (vy / vz) * focal))),
                        )
                        for vx, vy, vz in clipped
                    ]

                c = (int(row_col[j, 0]), int(row_col[j, 1]), int(row_col[j, 2]))
                pygame.draw.polygon(screen, c, poly)
                if wireframe:
                    ec = (min(255, c[0] + 35), min(255, c[1] + 35), min(255, c[2] + 40))
                    pygame.draw.polygon(screen, ec, poly, 1)

        if show_horizon_line:
            h_pts = []
            for h_alt, h_az in zip(self.horizon_alt, self.az_grid):
                px = math.cos(h_alt) * math.cos(h_az)
                py = math.cos(h_alt) * math.sin(h_az)
                pz = math.sin(h_alt)
                p = np.array([px, py, pz])
                zc = float(np.dot(p, fwd))
                if zc > 0.05:
                    xc = float(np.dot(p, right))
                    yc = float(np.dot(p, cam_up))
                    h_pts.append((cw / 2.0 + (xc / zc) * focal, ch / 2.0 - (yc / zc) * focal))
                else:
                    if len(h_pts) > 1:
                        pygame.draw.lines(screen, (90, 175, 220), False, h_pts, 2)
                    h_pts = []
            if len(h_pts) > 1:
                pygame.draw.lines(screen, (90, 175, 220), False, h_pts, 2)


def draw_telescopic_sun(screen, sx, sy, r_sun_exact, cw, ch):
    """Renderuje tarczę Słońca z koroną i pociemnieniem brzegowym przy każdym powiększeniu."""
    r_sun = max(4.0, r_sun_exact)
    halo_mult = 3.8 if r_sun < 20.0 else 2.5
    halo_r = int(min(max(r_sun * halo_mult, 22), max(cw, ch)))

    x0 = max(0, int(sx - halo_r))
    x1 = min(cw, int(sx + halo_r) + 1)
    y0 = max(0, int(sy - halo_r))
    y1 = min(ch, int(sy + halo_r) + 1)
    if x1 <= x0 or y1 <= y0:
        return

    w_box, h_box = x1 - x0, y1 - y0
    if r_sun < 18.0:
        grid_w, grid_h = max(8, w_box * 3), max(8, h_box * 3)
    else:
        ss = 1 if halo_r <= 180 else (2 if halo_r <= 450 else 3)
        grid_w, grid_h = max(2, w_box // ss), max(2, h_box // ss)

    xs = (np.linspace(x0, x1 - 1, grid_w, dtype=np.float32) - sx) / r_sun
    ys = (np.linspace(y0, y1 - 1, grid_h, dtype=np.float32) - sy) / r_sun
    gx, gy = np.meshgrid(xs, ys)
    dist = np.sqrt(gx * gx + gy * gy)

    img = np.zeros((grid_h, grid_w, 4), dtype=np.uint8)

    disk = dist <= 1.0
    if np.any(disk):
        mu = np.sqrt(np.clip(1.0 - dist[disk] ** 2, 0.0, 1.0))
        limb_dark = 0.45 + 0.55 * np.power(mu, 0.50)
        if r_sun > 18.0:
            granulation = 0.028 * np.sin(gx[disk] * 55.0) * np.cos(gy[disk] * 55.0)
            limb_dark = np.clip(limb_dark + granulation, 0.25, 1.05)
        img[disk, 0] = np.clip(255.0 * np.minimum(1.0, limb_dark * 1.06), 0, 255).astype(np.uint8)
        img[disk, 1] = np.clip(246.0 * limb_dark, 0, 255).astype(np.uint8)
        img[disk, 2] = np.clip(218.0 * np.power(limb_dark, 1.15), 0, 255).astype(np.uint8)
        img[disk, 3] = 255

    corona = (~disk) & (dist <= halo_mult)
    if np.any(corona):
        t_c = (dist[corona] - 1.0) / (halo_mult - 1.0)
        glow = np.exp(-2.6 * t_c) * (1.0 - t_c)
        img[corona, 0] = 255
        img[corona, 1] = 228
        img[corona, 2] = 165
        img[corona, 3] = np.clip(220.0 * glow, 0, 255).astype(np.uint8)

    surf = pygame.image.frombuffer(img.tobytes(), (grid_w, grid_h), "RGBA")
    if (grid_w, grid_h) != (w_box, h_box):
        surf = pygame.transform.smoothscale(surf, (w_box, h_box))
    screen.blit(surf, (x0, y0))


def draw_telescopic_earth(screen, ex, ey, r_earth_exact, cw, ch,
                          cam_right, cam_up, dir_earth_enu, sun_from_earth_enu,
                          moon_from_earth_enu, sun_dist_km,
                          ecef_axes_enu, cloud_offset,
                          eclipse_ring_factor=0.0, dark_side_exposure=1.0,
                          day_arr=None, night_mips=None, clouds_arr=None):
    """Wektorowy renderer tarczy Ziemi 3D z ciemną stroną nocną, zaćmieniami i obrotem W->E."""
    r_earth = max(6.5, r_earth_exact)
    pad = int(max(4, r_earth * 0.14))
    r_outer = r_earth + pad

    x0 = max(0, int(ex - r_outer))
    x1 = min(cw, int(ex + r_outer) + 1)
    y0 = max(0, int(ey - r_outer))
    y1 = min(ch, int(ey + r_outer) + 1)
    if x1 <= x0 or y1 <= y0:
        return

    w_box, h_box = x1 - x0, y1 - y0
    if r_earth < 24.0:
        grid_w, grid_h = max(8, w_box * 4), max(8, h_box * 4)
    else:
        ss = 1 if r_earth <= 160 else (2 if r_earth <= 420 else 3)
        grid_w, grid_h = max(2, w_box // ss), max(2, h_box // ss)

    xs = (np.linspace(x0, x1 - 1, grid_w, dtype=np.float32) - ex) / r_earth
    ys = (np.linspace(y0, y1 - 1, grid_h, dtype=np.float32) - ey) / r_earth
    gx, gy = np.meshgrid(xs, ys)
    dist_sq = gx * gx + gy * gy
    mask = dist_sq <= 1.0
    if not np.any(mask):
        return

    gz = np.zeros_like(dist_sq)
    gz[mask] = np.sqrt(1.0 - dist_sq[mask])

    # Prawoskrętna baza ekranowa tarczy Ziemi w układzie ENU obserwatora
    e_z_cam = -dir_earth_enu
    e_x_cam = cam_right - np.dot(cam_right, e_z_cam) * e_z_cam
    nx_norm = np.linalg.norm(e_x_cam)
    if nx_norm < 1e-6:
        e_x_cam = np.cross(cam_up, e_z_cam)
        nx_norm = np.linalg.norm(e_x_cam)
    e_x_cam /= nx_norm
    e_y_cam = np.cross(e_z_cam, e_x_cam)

    gx_m = gx[mask][:, None]
    gy_m = gy[mask][:, None]
    gz_m = gz[mask][:, None]

    # Zewnętrzny wektor normalny powierzchni kuli ziemskiej w układzie ENU
    n_enu = gx_m * e_x_cam[None, :] - gy_m * e_y_cam[None, :] + gz_m * e_z_cam[None, :]

    # Rzut na obracający się układ geograficzny Ziemi (ECEF)
    x_ecef, y_ecef, z_ecef = ecef_axes_enu
    px = n_enu @ x_ecef
    py = n_enu @ y_ecef
    pz = n_enu @ z_ecef

    lat_pt = np.arcsin(np.clip(pz, -1.0, 1.0))
    lon_pt = np.arctan2(py, px)

    u = (lon_pt + np.pi) / (2.0 * np.pi)
    v = (np.pi * 0.5 - lat_pt) / np.pi

    # 1. Tekstura dzienna Ziemi (earth_day8K.jpg)
    if day_arr is not None:
        dh, dw = day_arr.shape[:2]
        tx = (u * dw).astype(np.int32) % dw
        ty = np.clip((v * dh).astype(np.int32), 0, dh - 1)
        day_rgb = day_arr[ty, tx].astype(np.float32)
    else:
        continent = (
            np.sin(lon_pt * 2.1 + 0.4) * np.cos(lat_pt * 2.3)
            + 0.55 * np.cos(lon_pt * 4.7 - 1.1) * np.sin(lat_pt * 3.8 + 0.3)
            + 0.30 * np.sin(lon_pt * 9.0 + lat_pt * 7.0)
        )
        is_land = continent > 0.18
        is_ice = np.abs(lat_pt) > np.radians(72.0 - 8.0 * continent)
        day_rgb = np.empty((px.shape[0], 3), dtype=np.float32)
        day_rgb[:] = (22.0, 72.0, 158.0)
        day_rgb[is_land] = (64.0, 118.0, 62.0)
        day_rgb[is_ice] = (235.0, 242.0, 248.0)

    # 2. Tekstura nocna Ziemi — ciemniejsze tło + wyraźne światła miast (earth_night8K.jpg)
    if night_mips:
        base_w = night_mips[0].shape[1]
        texels_per_px = base_w / max(1.0, 2.0 * math.pi * r_earth)
        mip_idx = int(np.clip(round(math.log2(max(1.0, texels_per_px))), 0, len(night_mips) - 1))
        night_tex = night_mips[mip_idx]
        nh, nw = night_tex.shape[:2]
        nx = (u * nw).astype(np.int32) % nw
        ny = np.clip((v * nh).astype(np.int32), 0, nh - 1)
        raw_night = night_tex[ny, nx].astype(np.float32) / 255.0
        clean_night = np.clip((raw_night - 0.055) / 0.945, 0.0, 1.0)
        night_rgb = np.power(clean_night, 0.88) * 255.0 * (1.15 * dark_side_exposure)
    else:
        continent = (
            np.sin(lon_pt * 2.1 + 0.4) * np.cos(lat_pt * 2.3)
            + 0.55 * np.cos(lon_pt * 4.7 - 1.1) * np.sin(lat_pt * 3.8 + 0.3)
        )
        urban = (
            (continent > 0.22)
            & (np.abs(lat_pt) < np.radians(60.0))
            & (np.sin(lon_pt * 28.0) * np.cos(lat_pt * 34.0) > 0.65)
        )
        night_rgb = np.zeros_like(day_rgb)
        night_rgb[urban] = (235.0 * dark_side_exposure, 175.0 * dark_side_exposure, 80.0 * dark_side_exposure)

    # 3. Faza Ziemi oraz cień Księżyca na Ziemi (zaćmienie Słońca na Ziemi)
    cos_sun = n_enu @ sun_from_earth_enu
    twilight_t = np.clip((cos_sun + 0.07) / 0.15, 0.0, 1.0)
    day_blend = twilight_t * twilight_t * (3.0 - 2.0 * twilight_t)

    sun_diffuse = np.power(np.clip(cos_sun, 0.0, 1.0), 0.78)

    if np.dot(moon_from_earth_enu, sun_from_earth_enu) > 0.0:
        pts_earth_km = R_EARTH * n_enu
        rel_to_moon = pts_earth_km - moon_from_earth_enu[None, :]
        along_sun = rel_to_moon @ sun_from_earth_enu
        behind_moon = along_sun < 0.0
        if np.any(behind_moon):
            dist_behind = -along_sun[behind_moon]
            perp_vec = rel_to_moon[behind_moon] + dist_behind[:, None] * sun_from_earth_enu[None, :]
            perp_dist = np.linalg.norm(perp_vec, axis=-1)

            r_penumbra = R_MOON + dist_behind * (R_SUN + R_MOON) / max(1.0, sun_dist_km)
            r_umbra = np.maximum(0.0, R_MOON - dist_behind * (R_SUN - R_MOON) / max(1.0, sun_dist_km))

            in_pen = perp_dist < r_penumbra
            if np.any(in_pen):
                pen_t = np.clip(
                    (perp_dist[in_pen] - r_umbra[in_pen]) / np.maximum(r_penumbra[in_pen] - r_umbra[in_pen], 1.0),
                    0.0,
                    1.0,
                )
                shadow_atten = 0.08 + 0.92 * (pen_t * pen_t * (3.0 - 2.0 * pen_t))
                idx_behind = np.nonzero(behind_moon)[0]
                sun_diffuse[idx_behind[in_pen]] *= shadow_atten

    terminator_glow = np.exp(-((cos_sun - 0.01) / 0.095) ** 2) * (cos_sun > -0.08)

    lit_day_rgb = day_rgb * (0.02 + 0.98 * sun_diffuse)[:, None]
    lit_day_rgb[:, 0] += 36.0 * terminator_glow
    lit_day_rgb[:, 1] += 12.0 * terminator_glow

    # 4. Równomierny i zapętlony dryf chmur z zachodu na wschód (earth_clouds8K.jpg)
    if clouds_arr is not None:
        ch_t, cw_t = clouds_arr.shape[:2]
        u_cloud = (u - cloud_offset) % 1.0
        fx = u_cloud * cw_t
        fy = np.clip(v * (ch_t - 1), 0.0, ch_t - 1.0001)

        x0_c = np.floor(fx).astype(np.int32) % cw_t
        x1_c = (x0_c + 1) % cw_t
        y0_c = np.floor(fy).astype(np.int32)
        y1_c = np.minimum(y0_c + 1, ch_t - 1)

        wx = fx - np.floor(fx)
        wy = fy - y0_c

        c00 = clouds_arr[y0_c, x0_c, 0].astype(np.float32)
        c10 = clouds_arr[y0_c, x1_c, 0].astype(np.float32)
        c01 = clouds_arr[y1_c, x0_c, 0].astype(np.float32)
        c11 = clouds_arr[y1_c, x1_c, 0].astype(np.float32)

        c_raw = (
            (c00 * (1.0 - wx) + c10 * wx) * (1.0 - wy)
            + (c01 * (1.0 - wx) + c11 * wx) * wy
        ) / 255.0

        cloud_alpha = np.power(np.clip((c_raw - 0.04) / 0.96, 0.0, 1.0), 0.90) * 0.92

        cloud_lit_r = 252.0 * (0.03 + 0.97 * sun_diffuse) + 46.0 * terminator_glow
        cloud_lit_g = 253.0 * (0.03 + 0.97 * sun_diffuse) + 16.0 * terminator_glow
        cloud_lit_b = 255.0 * (0.04 + 0.96 * sun_diffuse)
        cloud_lit_rgb = np.stack([cloud_lit_r, cloud_lit_g, cloud_lit_b], axis=-1)

        cf_day = cloud_alpha[:, None]
        lit_day_rgb = lit_day_rgb * (1.0 - cf_day) + cloud_lit_rgb * cf_day

        night_rgb = night_rgb * (1.0 - 0.55 * cloud_alpha)[:, None]

    # Połączenie ciemnej strony nocnej (światła miast) i strony dziennej
    twilight_cities = np.clip((0.04 - cos_sun) / 0.14, 0.0, 1.0) ** 1.4
    out_rgb = lit_day_rgb * day_blend[:, None] + night_rgb * twilight_cities[:, None]

    # Poświata atmosferyczna na krawędzi tarczy (niebieska w dzień, czerwona przy zaćmieniu Słońca przez Ziemię)
    limb_geom = np.power(1.0 - gz[mask], 2.6)
    day_limb = limb_geom * np.clip(cos_sun + 0.22, 0.0, 1.0) * (1.0 - 0.75 * eclipse_ring_factor)
    ecl_limb = limb_geom * eclipse_ring_factor

    out_rgb[:, 0] += 75.0 * day_limb + 245.0 * ecl_limb
    out_rgb[:, 1] += 155.0 * day_limb + 95.0 * ecl_limb
    out_rgb[:, 2] += 250.0 * day_limb + 35.0 * ecl_limb

    img = np.zeros((grid_h, grid_w, 4), dtype=np.uint8)
    img[mask, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    img[mask, 3] = 255

    # Miękka zewnętrzna aureola atmosferyczna wokół tarczy Ziemi
    halo_mask = (~mask) & (dist_sq <= 1.28)
    if np.any(halo_mask):
        dist_h = np.sqrt(dist_sq[halo_mask])
        h_fade = np.clip(1.0 - (dist_h - 1.0) / 0.13, 0.0, 1.0) ** 2
        n_halo = (
            gx[halo_mask][:, None] * e_x_cam[None, :]
            - gy[halo_mask][:, None] * e_y_cam[None, :]
        )
        sun_facing = np.clip((n_halo @ sun_from_earth_enu) + 0.30, 0.04, 1.0)
        halo_strength = np.maximum(sun_facing, 0.85 * eclipse_ring_factor)

        hr = int(75 * (1.0 - eclipse_ring_factor) + 235 * eclipse_ring_factor)
        hg = int(155 * (1.0 - eclipse_ring_factor) + 88 * eclipse_ring_factor)
        hb = int(250 * (1.0 - eclipse_ring_factor) + 32 * eclipse_ring_factor)

        img[halo_mask, 0] = hr
        img[halo_mask, 1] = hg
        img[halo_mask, 2] = hb
        img[halo_mask, 3] = np.clip(150.0 * h_fade * halo_strength, 0, 255).astype(np.uint8)

    surf = pygame.image.frombuffer(img.tobytes(), (grid_w, grid_h), "RGBA")
    if (grid_w, grid_h) != (w_box, h_box):
        surf = pygame.transform.smoothscale(surf, (w_box, h_box))
    screen.blit(surf, (x0, y0))


def load_year_data(year):
    filepath = f"coords/{year}.csv"
    if os.path.exists(filepath):
        times = []
        rows = []
        with open(filepath, mode="r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                times.append(datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"))
                rows.append([float(x) for x in row[1:7]])
        coords = np.array(rows, dtype=np.float64)

        moon_dist_med = float(np.median(np.linalg.norm(coords[:, 3:6], axis=1)))
        if moon_dist_med > 1e7:
            coords /= 1000.0
        elif moon_dist_med < 1.0:
            coords *= 149597870.7

        print(f"[OK] Wczytano dane dla roku {year} z: {filepath}")
    else:
        print(f"[OSTRZEŻENIE] Nie znaleziono '{filepath}'. Generuję dane testowe dla roku {year}...")
        start_dt = datetime(year, 1, 1, 0, 0, 0)
        end_dt = datetime(year + 1, 1, 1, 0, 0, 0)
        n_hours = int((end_dt - start_dt).total_seconds() // 3600)
        times = [start_dt + timedelta(hours=h) for h in range(n_hours)]
        t_days = np.array([(t - J2000).total_seconds() / 86400.0 for t in times], dtype=np.float64)

        w_sun = 2 * np.pi / 365.256
        sun_x = 1.496e8 * np.cos(w_sun * t_days + 1.74)
        sun_y = 1.496e8 * np.sin(w_sun * t_days + 1.74)
        sun_z = np.zeros_like(t_days)

        w_moon = 2 * np.pi / SIDEREAL_MONTH
        inc = math.radians(5.145)
        moon_x = 384400 * np.cos(w_moon * t_days)
        moon_y = 384400 * np.sin(w_moon * t_days) * np.cos(inc)
        moon_z = 384400 * np.sin(w_moon * t_days) * np.sin(inc)

        coords = np.column_stack([sun_x, sun_y, sun_z, moon_x, moon_y, moon_z])

    d_j2000_total = np.array([(t - J2000).total_seconds() / 86400.0 for t in times], dtype=np.float64)
    return {
        "times": times,
        "coords": coords,
        "d_j2000_total": d_j2000_total,
    }


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def approx_delta_t_days(d_j2000_utc: float) -> float:
    """Przybliża różnicę TT - UTC (w dniach) dla lat 2000–2100."""
    year = 2000.0 + d_j2000_utc / 365.25
    t = year - 2000.0
    if year <= 2026.0:
        dt_sec = 63.8 + 0.21 * t
    else:
        u = year - 2026.0
        dt_sec = 69.3 + 0.35 * u + 0.0035 * (u * u)
    return dt_sec / 86400.0


def get_lunar_body_matrix(d_j2000_utc: float):
    """
    Zwraca macierz obrotu z ekliptyki J2000 do układu kartograficznego Księżyca
    Mean Earth / Polar Axis (MOON_ME) zgodnie ze standardem IAU (Archinal et al.),
    z uwzględnieniem precesji od epoki J2000, libracji fizycznych (E1..E13) oraz TT-UTC.
    """
    d = d_j2000_utc + approx_delta_t_days(d_j2000_utc)
    T = d / 36525.0

    E1 = math.radians(125.045 - 0.0529921 * d)
    E2 = math.radians(250.089 - 0.1059842 * d)
    E3 = math.radians(260.008 + 13.0120009 * d)
    E4 = math.radians(176.625 + 13.3407154 * d)
    E5 = math.radians(357.529 + 0.9856003 * d)
    E6 = math.radians(311.589 + 26.4057084 * d)
    E7 = math.radians(134.963 + 13.0649930 * d)
    E8 = math.radians(276.617 + 0.3287146 * d)
    E9 = math.radians(34.226 + 1.7484877 * d)
    E10 = math.radians(15.134 - 0.1589763 * d)
    E11 = math.radians(119.743 + 0.0036096 * d)
    E12 = math.radians(239.961 + 0.1643573 * d)
    E13 = math.radians(25.053 + 12.9590088 * d)

    alpha0 = math.radians(
        269.9949 + 0.0031 * T
        - 3.8787 * math.sin(E1)
        - 0.1204 * math.sin(E2)
        + 0.0700 * math.sin(E3)
        - 0.0172 * math.sin(E4)
        + 0.0072 * math.sin(E6)
        - 0.0052 * math.sin(E10)
        + 0.0043 * math.sin(E13)
    )
    delta0 = math.radians(
        66.5392 + 0.0130 * T
        + 1.5419 * math.cos(E1)
        + 0.0239 * math.cos(E2)
        - 0.0278 * math.cos(E3)
        + 0.0068 * math.cos(E4)
        - 0.0029 * math.cos(E6)
        + 0.0009 * math.cos(E7)
        + 0.0008 * math.cos(E10)
        - 0.0009 * math.cos(E13)
    )
    W = math.radians(
        38.3213 + 13.17635815 * d - 1.4e-12 * (d * d)
        + 3.5610 * math.sin(E1)
        + 0.1208 * math.sin(E2)
        - 0.0642 * math.sin(E3)
        + 0.0158 * math.sin(E4)
        + 0.0252 * math.sin(E5)
        - 0.0066 * math.sin(E6)
        - 0.0047 * math.sin(E7)
        - 0.0046 * math.sin(E8)
        + 0.0028 * math.sin(E9)
        + 0.0052 * math.sin(E10)
        + 0.0040 * math.sin(E11)
        + 0.0019 * math.sin(E12)
        - 0.0044 * math.sin(E13)
    )

    R_icrf_to_me = rot_z(-W) @ rot_x(-(math.pi / 2.0 - delta0)) @ rot_z(-(alpha0 + math.pi / 2.0))
    return R_icrf_to_me @ rot_x(EPS_J2000)


def get_topocentric_vectors(year_data, time_idx_float, lat_deg, lon_deg, obs_radius_km=R_MOON):
    times = year_data["times"]
    coords = year_data["coords"]
    d_j2000_arr = year_data["d_j2000_total"]

    idx0 = int(math.floor(time_idx_float))
    idx1 = min(idx0 + 1, len(times) - 1)
    frac = time_idx_float - idx0

    d_j2000 = d_j2000_arr[idx0] * (1.0 - frac) + d_j2000_arr[idx1] * frac
    row_interp = coords[idx0] * (1.0 - frac) + coords[idx1] * frac

    sun_geo = row_interp[0:3]
    moon_geo = row_interp[3:6]

    earth_seleno_ecl = -moon_geo
    sun_seleno_ecl = sun_geo - moon_geo

    R_body = get_lunar_body_matrix(d_j2000)
    earth_body = R_body @ earth_seleno_ecl
    sun_body = R_body @ sun_seleno_ecl

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    obs_body = obs_radius_km * np.array([
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    ])

    vec_earth = earth_body - obs_body
    vec_sun = sun_body - obs_body

    up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.cross(up, east)

    def to_alt_az(v):
        dist = np.linalg.norm(v)
        alt = math.asin(max(-1.0, min(1.0, np.dot(v, up) / dist)))
        az = math.atan2(np.dot(v, east), np.dot(v, north)) % (2 * math.pi)
        return alt, az, dist

    earth_alt, earth_az, earth_dist = to_alt_az(vec_earth)
    sun_alt, sun_az, sun_dist = to_alt_az(vec_sun)

    def ecl_to_enu(v_ecl):
        v_b = R_body @ v_ecl
        return np.array([v_b @ north, v_b @ east, v_b @ up])

    sun_dist_from_earth = float(np.linalg.norm(sun_geo))
    sun_from_earth_ecl = sun_geo / sun_dist_from_earth
    sun_from_earth_enu = ecl_to_enu(sun_from_earth_ecl)
    moon_from_earth_enu = ecl_to_enu(moon_geo)

    T_cent = d_j2000 / 36525.0
    zeta_a = math.radians((2306.2181 * T_cent + 0.30188 * (T_cent ** 2)) / 3600.0)
    z_a = math.radians((2306.2181 * T_cent + 1.09468 * (T_cent ** 2)) / 3600.0)
    theta_a = math.radians((2004.3109 * T_cent - 0.42665 * (T_cent ** 2)) / 3600.0)
    R_prec_icrf_to_mod = rot_z(-z_a) @ rot_y(theta_a) @ rot_z(-zeta_a)

    gmst = math.radians((280.46061837 + 360.98564736629 * d_j2000) % 360.0)
    R_icrf_to_ecef = rot_z(gmst) @ R_prec_icrf_to_mod
    R_ecl_to_ecef = R_icrf_to_ecef @ rot_x(EPS_J2000)

    ecef_axes_enu = (
        ecl_to_enu(R_ecl_to_ecef[0]),
        ecl_to_enu(R_ecl_to_ecef[1]),
        ecl_to_enu(R_ecl_to_ecef[2]),
    )

    current_time = times[idx0] + (times[idx1] - times[idx0]) * frac
    return {
        "time": current_time,
        "d_j2000": d_j2000,
        "R_body": R_body,
        "earth": (earth_alt, earth_az, earth_dist),
        "sun": (sun_alt, sun_az, sun_dist),
        "obs_bases": (north, east, up),
        "sun_from_earth_enu": sun_from_earth_enu,
        "moon_from_earth_enu": moon_from_earth_enu,
        "sun_dist_from_earth": sun_dist_from_earth,
        "ecef_axes_enu": ecef_axes_enu,
    }


class Slider:
    def __init__(self, x, y, w, h, min_val, max_val, val, label, fmt="{:.2f}", is_int=False, power=1.0):
        self.rect = pygame.Rect(x, y, w, h)
        self.min_val, self.max_val, self.val = min_val, max_val, val
        self.label, self.fmt, self.is_int = label, fmt, is_int
        self.power = power
        self.dragging = False

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
        curved = ratio ** self.power
        val = self.min_val + curved * (self.max_val - self.min_val)
        self.val = int(round(val)) if self.is_int else val

    def draw(self, screen, font, custom_text=None):
        pygame.draw.rect(screen, (60, 65, 75), self.rect, border_radius=4)
        if self.max_val > self.min_val:
            linear_ratio = max(0.0, min(1.0, (self.val - self.min_val) / (self.max_val - self.min_val)))
            ratio = linear_ratio ** (1.0 / self.power)
        else:
            ratio = 0.0
        fill_rect = pygame.Rect(self.rect.x, self.rect.y, int(self.rect.width * ratio), self.rect.height)
        pygame.draw.rect(screen, (100, 160, 230), fill_rect, border_radius=4)
        pygame.draw.circle(screen, (240, 245, 255), (self.rect.x + int(self.rect.width * ratio), self.rect.centery), 8)

        val_str = custom_text if custom_text else (str(int(self.val)) if self.is_int else self.fmt.format(self.val))
        txt = font.render(f"{self.label}: {val_str}", True, (230, 230, 230))
        screen.blit(txt, (self.rect.x, self.rect.y - 20))


def format_height_m(height_m: float) -> str:
    if height_m < 1000.0:
        return f"{height_m:.1f} m"
    return f"{height_m / 1000.0:.2f} km"


def main():
    pygame.init()
    W, H = 1280, 800
    screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
    pygame.display.set_caption("Lunar Stellarium - Tekstura Powierzchni Księżyca i Zoom Teleskopowy")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Consolas", 15)
    font_big = pygame.font.SysFont("Consolas", 18, bold=True)

    dem_km, albedo_rgb, dem_source = load_or_download_lunar_maps()
    terrain_3d = LunarTerrain3D(dem_km, albedo_rgb)
    wireframe_mode = False
    show_horizon_line = True

    earth_day_arr, earth_night_mips, earth_clouds_arr = load_earth_textures()

    cam_az = 0.0
    cam_alt = math.radians(15.0)
    base_fov = math.radians(75.0)
    fov = base_fov
    target_fov = base_fov
    MIN_FOV = math.radians(0.20)
    MAX_FOV = math.radians(115.0)

    dragging_sky = False
    last_mouse = (0, 0)
    playing = False
    play_speed = 24.0
    anim_time = 0.0
    status_msg = ""
    status_timer = 0.0

    current_year = 2000
    year_data = load_year_data(current_year)

    slider_year = Slider(30, H - 45, 250, 10, 2000, 2100, current_year, "Rok", is_int=True)
    slider_time = Slider(300, H - 45, W - 330, 10, 0, len(year_data["times"]) - 1, 0, "Czas w roku")
    slider_lat = Slider(30, 40, 240, 10, -90.0, 90.0, -43.31, "Szerokość (Lat)", "{:+.2f}°")
    slider_lon = Slider(30, 90, 240, 10, -180.0, 180.0, -11.36, "Długość (Lon)", "{:+.2f}°")
    slider_height = Slider(30, 140, 240, 10, 2.0, 50000.0, 2.0, "Wysokość nad pow.", power=3.0)
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
            + (math.atan2(dx_px, focal_old) - math.atan2(dx_px, focal_new)) / max(0.25, math.cos(cam_alt))
        ) % (2.0 * math.pi)
        cam_alt = max(
            -math.pi / 2.0 + 0.01,
            min(math.pi / 2.0 - 0.01, cam_alt + (math.atan2(dy_px, focal_old) - math.atan2(dy_px, focal_new))),
        )

    def get_camera_basis():
        fwd = np.array([
            math.cos(cam_alt) * math.cos(cam_az),
            math.cos(cam_alt) * math.sin(cam_az),
            math.sin(cam_alt),
        ])
        right = np.array([-math.sin(cam_az), math.cos(cam_az), 0.0])
        cam_up = np.array([
            -math.sin(cam_alt) * math.cos(cam_az),
            -math.sin(cam_alt) * math.sin(cam_az),
            math.cos(cam_alt),
        ])
        return fwd, right, cam_up

    def project_point(alt, az, cw, ch, cam_basis):
        px = math.cos(alt) * math.cos(az)
        py = math.cos(alt) * math.sin(az)
        pz = math.sin(alt)

        fwd, right, cam_up = cam_basis
        p = np.array([px, py, pz])
        z_cam = np.dot(p, fwd)
        if z_cam <= 0.05:
            return None

        x_cam = np.dot(p, right)
        y_cam = np.dot(p, cam_up)
        focal = (ch / 2.0) / math.tan(fov / 2.0)
        return (cw / 2.0 + (x_cam / z_cam) * focal, ch / 2.0 - (y_cam / z_cam) * focal, z_cam, focal)

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
        anim_time += dt
        cw, ch = screen.get_size()
        if status_timer > 0.0:
            status_timer = max(0.0, status_timer - dt)

        slider_year.rect.y = ch - 45
        slider_time.rect.y = ch - 45
        slider_time.rect.width = max(200, cw - 330)

        old_year = current_year
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if slider_year.handle_event(event):
                current_year = int(slider_year.val)
            if slider_time.handle_event(event):
                continue
            if slider_lat.handle_event(event) or slider_lon.handle_event(event):
                location_name = "Własne współrzędne"
                continue
            if slider_height.handle_event(event):
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
                    if dist_ang < math.radians(2.0):
                        target_fov = math.radians(3.2)
                elif event.key == pygame.K_s:
                    dist_ang = math.hypot(
                        cam_alt - data["sun"][0],
                        (cam_az - data["sun"][1] + math.pi) % (2 * math.pi) - math.pi,
                    )
                    cam_alt, cam_az = data["sun"][0], data["sun"][1]
                    if dist_ang < math.radians(2.0):
                        target_fov = math.radians(1.4)
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
                    terrain_3d.export_horizon_csv("horizon.csv")
                    status_msg = "Zapisano profil horyzontu: horizon.csv"
                    status_timer = 3.5
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

        terrain_3d.update_observer(slider_lat.val, slider_lon.val, eye_height_m=slider_height.val)

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
        sun_from_earth_enu = data["sun_from_earth_enu"]
        moon_from_earth_enu = data["moon_from_earth_enu"]
        sun_dist_from_earth = data["sun_dist_from_earth"]
        ecef_axes_enu = data["ecef_axes_enu"]
        d_j2000 = data["d_j2000"]

        earth_hor = terrain_3d.get_horizon_at_azimuth(earth_az)
        sun_hor = terrain_3d.get_horizon_at_azimuth(sun_az)
        cam_hor = terrain_3d.get_horizon_at_azimuth(cam_az)

        ang_earth = math.asin(min(1.0, R_EARTH / earth_dist))
        ang_sun = math.asin(min(1.0, R_SUN / sun_dist))

        dir_earth_enu = np.array([
            math.cos(earth_alt) * math.cos(earth_az),
            math.cos(earth_alt) * math.sin(earth_az),
            math.sin(earth_alt),
        ])
        dir_sun_enu = np.array([
            math.cos(sun_alt) * math.cos(sun_az),
            math.cos(sun_alt) * math.sin(sun_az),
            math.sin(sun_alt),
        ])

        sun_horizon_vis = horizon_visible_fraction(sun_alt, sun_hor, ang_sun)

        if earth_dist < sun_dist:
            sep_earth_sun = math.acos(max(-1.0, min(1.0, float(np.dot(dir_earth_enu, dir_sun_enu)))))
            sun_eclipse_occ = circle_overlap_fraction(ang_sun, ang_earth, sep_earth_sun)
            eclipse_ring_factor = max(0.0, min(1.0, 1.0 - max(0.0, sep_earth_sun - ang_earth) / (2.2 * ang_sun)))
            eclipse_ring_factor = eclipse_ring_factor * eclipse_ring_factor * (3.0 - 2.0 * eclipse_ring_factor)
        else:
            sun_eclipse_occ = 0.0
            eclipse_ring_factor = 0.0

        sun_eclipse_vis = 1.0 - sun_eclipse_occ
        sun_effective_vis = sun_horizon_vis * sun_eclipse_vis
        eclipse_red_glow = sun_horizon_vis * sun_eclipse_occ
        dark_side_exposure = 0.85 + 0.35 * (1.0 - sun_effective_vis)

        cam_basis = get_camera_basis()
        _, cam_right, cam_up = cam_basis

        screen.fill((5, 7, 12))

        # 1. Gwiazdy
        stars_body = (R_body @ stars_ecl.T).T
        s_n = stars_body @ north
        s_e = stars_body @ east
        s_u = stars_body @ up

        star_alts = np.arcsin(np.clip(s_u, -1.0, 1.0))
        star_azs = np.arctan2(s_e, s_n) % (2 * np.pi)

        for s_alt, s_az, mag in zip(star_alts, star_azs, star_mags):
            if s_alt > -0.1:
                proj = project_point(s_alt, s_az, cw, ch, cam_basis)
                if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                    screen.set_at((int(proj[0]), int(proj[1])), (mag, mag, mag))

        # 2. Siatka azymutalna
        grid_color = (25, 35, 50)
        for a_deg in range(0, 90, 30):
            a_rad = math.radians(a_deg)
            pts = [project_point(a_rad, math.radians(z), cw, ch, cam_basis) for z in range(0, 365, 5)]
            pts_xy = [(p[0], p[1]) if p else None for p in pts]
            for i in range(len(pts_xy) - 1):
                if pts_xy[i] and pts_xy[i + 1]:
                    pygame.draw.line(screen, grid_color, pts_xy[i], pts_xy[i + 1], 1)

        # 3. SŁOŃCE (teleskopowe pociemnienie brzegowe + korona)
        sun_proj = project_point(sun_alt, sun_az, cw, ch, cam_basis)
        if sun_proj:
            sx, sy, z_cam, focal = sun_proj
            r_sun_exact = math.tan(ang_sun) * focal / z_cam
            draw_telescopic_sun(screen, sx, sy, r_sun_exact, cw, ch)
            r_label = max(6, int(r_sun_exact))
            if 0 <= sx + r_label + 6 < cw and 0 <= sy - 8 < ch:
                screen.blit(font.render("Słońce", True, (255, 230, 150)), (sx + r_label + 6, sy - 8))

        # 4. ZIEMIA (poprawna orientacja geograficzna, obrót W->E, ciemna noc, zaćmienia)
        earth_proj = project_point(earth_alt, earth_az, cw, ch, cam_basis)
        if earth_proj:
            ex, ey, z_cam, focal = earth_proj
            r_earth_exact = math.tan(ang_earth) * focal / z_cam
            d_rel = d_j2000 - year_data["d_j2000_total"][0]
            cloud_offset = (d_rel * 0.015 + anim_time * 0.0012) % 1.0
            draw_telescopic_earth(
                screen, ex, ey, r_earth_exact, cw, ch,
                cam_right, cam_up, dir_earth_enu, sun_from_earth_enu,
                moon_from_earth_enu, sun_dist_from_earth,
                ecef_axes_enu, cloud_offset,
                eclipse_ring_factor=eclipse_ring_factor,
                dark_side_exposure=dark_side_exposure,
                day_arr=earth_day_arr,
                night_mips=earth_night_mips,
                clouds_arr=earth_clouds_arr,
            )
            r_elabel = max(8, int(r_earth_exact))
            if 0 <= ex + r_elabel + 8 < cw and 0 <= ey - 8 < ch:
                screen.blit(font.render("Ziemia", True, (130, 200, 255)), (ex + r_elabel + 8, ey - 8))

        # 5. MODEL 3D TEKSTUROWANEJ POWIERZCHNI KSIĘŻYCA (KARTEZJAŃSKA SIATKA PROSTOKĄTNA)
        terrain_3d.draw_3d(
            screen, cw, ch, cam_alt, cam_az, fov,
            sun_alt, sun_az, earth_alt,
            sun_effective_vis=sun_effective_vis,
            eclipse_red_glow=eclipse_red_glow,
            wireframe=wireframe_mode,
            show_horizon_line=show_horizon_line,
        )

        # 6. Kierunki świata nad lokalnym horyzontem topograficznym
        for label, deg in [("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315)]:
            az_r = math.radians(deg)
            h_alt = terrain_3d.get_horizon_at_azimuth(az_r) + max(math.radians(1.2), fov * 0.02)
            proj = project_point(h_alt, az_r, cw, ch, cam_basis)
            if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                col = (255, 90, 90) if label == "N" else (210, 220, 235)
                txt = font_big.render(label, True, col)
                screen.blit(txt, (proj[0] - txt.get_width() // 2, proj[1] - txt.get_height() // 2))

        # 7. HUD
        zoom_mag = base_fov / fov
        height_str = format_height_m(slider_height.val)

        earth_vis = "WIDOCZNA" if earth_alt + ang_earth > earth_hor else "POD HORYZONTEM"
        if sun_horizon_vis <= 0.0:
            sun_vis = "POD HORYZONTEM"
        elif sun_eclipse_occ >= 0.995:
            sun_vis = "ZAĆMIENIE PRZEZ ZIEMIĘ 100%"
        elif sun_eclipse_occ > 0.01:
            sun_vis = f"ZAĆMIENIE {sun_eclipse_occ * 100:.0f}%"
        elif sun_horizon_vis < 0.995:
            sun_vis = f"NA HORYZONCIE ({sun_horizon_vis * 100:.0f}%)"
        else:
            sun_vis = "WIDOCZNE"

        info_lines = [
            f"Lokacja: {location_name} | DEM: {dem_source}",
            f"Teren: {terrain_3d.obs_elev_km:+.3f} km | Wys. obs.: {height_str} | Zoom: {zoom_mag:.1f}x",
            f"Kamera: Az {math.degrees(cam_az):.2f}° | Alt {math.degrees(cam_alt):+.2f}° (Hor: {math.degrees(cam_hor):+.2f}°)",
            "-" * 62,
            f"ZIEMIA: Alt {math.degrees(earth_alt):+6.2f}° | Az {math.degrees(earth_az):6.2f}° [{earth_vis}]",
            f"SŁOŃCE: Alt {math.degrees(sun_alt):+6.2f}° | Az {math.degrees(sun_az):6.2f}° [{sun_vis}]",
            "-" * 62,
            "[Scroll / +/-] Zoom (do 375x) | [R] Reset zoomu | [Spacja] Play",
            "[E] Ziemia (2x = zoom) | [S] Słońce (2x = zoom) | [L] Horyzont",
            "[M] Siatka 3D | [H] Linia horyzontu | [C] Zapisz horizon.csv",
            "[1-5] Lokacje Księżyca",
        ]

        panel_w = 635
        extra_h = 24 if status_timer > 0.0 else 0
        panel_surf = pygame.Surface((panel_w, len(info_lines) * 20 + 16 + extra_h), pygame.SRCALPHA)
        panel_surf.fill((15, 20, 30, 195))
        screen.blit(panel_surf, (cw - panel_w - 15, 15))

        for i, line in enumerate(info_lines):
            screen.blit(font.render(line, True, (210, 215, 225)), (cw - panel_w - 5, 22 + i * 20))

        if status_timer > 0.0:
            screen.blit(
                font.render(status_msg, True, (120, 235, 150)),
                (cw - panel_w - 5, 22 + len(info_lines) * 20 + 4),
            )

        slider_year.draw(screen, font)
        slider_time.draw(screen, font, data["time"].strftime("%Y-%m-%d %H:%M UTC"))
        slider_lat.draw(screen, font)
        slider_lon.draw(screen, font)
        slider_height.draw(screen, font, height_str)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
