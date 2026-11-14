import os
import sys
import csv
import math
import urllib.request
from datetime import datetime, timedelta
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

LOLA_DEM_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e1/Moon_LRO_LOLA_global_LDEM_1024.jpg/1280px-Moon_LRO_LOLA_global_LDEM_1024.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/e/e1/Moon_LRO_LOLA_global_LDEM_1024.jpg",
]

LRO_COLOR_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d1/Moon_LRO_WAC_global_mosaic_303ppd_v02.jpg/1280px-Moon_LRO_WAC_global_mosaic_303ppd_v02.jpg",
]

EARTH_DAY_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/Blue_Marble_2002.png/1280px-Blue_Marble_2002.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Equirectangular_projection_SW.jpg/1280px-Equirectangular_projection_SW.jpg",
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


def smooth_dem_2d(dem: np.ndarray, sigma: float = 1.8) -> np.ndarray:
    """Separowalny filtr Gaussa 2D wygładzający 8-bitowe schodki kwantyzacji na horyzoncie."""
    radius = max(1, int(math.ceil(2.5 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= np.sum(kernel)

    pad_x = np.pad(dem, ((0, 0), (radius, radius)), mode="wrap")
    blur_x = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="valid"), axis=1, arr=pad_x)

    pad_y = np.pad(blur_x, ((radius, radius), (0, 0)), mode="edge")
    blur_xy = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="valid"), axis=0, arr=pad_y)
    return blur_xy.astype(np.float32)


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
    """Wczytuje lub pobiera globalną mapę wysokości (DEM) oraz teksturę powierzchni Księżyca."""
    os.makedirs("Textures", exist_ok=True)
    dem_cache = os.path.join("Textures", "moon_dem_v2.npy")
    dem_img = os.path.join("Textures", "moon_dem.jpg")
    alb_cache = os.path.join("Textures", "moon_albedo_v2.npy")
    alb_img = os.path.join("Textures", "moon_color.jpg")

    if os.path.exists(dem_cache):
        dem = np.load(dem_cache)
        dem_src = "LOLA DEM (wygładzony)"
    else:
        _download_first_available(LOLA_DEM_URLS, dem_img, "Mapa wysokości NASA LOLA DEM")
        if os.path.exists(dem_img):
            try:
                surf = pygame.image.load(dem_img)
                arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)
                gray = arr[:, :, 0].astype(np.float32)
                raw_dem = LOLA_MIN_KM + (gray / 255.0) * (LOLA_MAX_KM - LOLA_MIN_KM)
                dem = smooth_dem_2d(raw_dem, sigma=1.8)
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
        if custom_tex is None and _download_first_available(LRO_COLOR_URLS, alb_img, "Tekstura powierzchni NASA LRO WAC"):
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

    night_path = next((p for p in ["Textures/earrth_night8K.jpg", "Textures/earth_night8K.jpg", "Textures/earth_night8K.png", "Textures/earth_night.jpg"] if os.path.exists(p)), None)
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


def build_regolith_detail_tiles(size: int = 512):
    """Generuje bezszwową mapę mikro-kraterów, kamieni i wypukłości regolitu (buforowaną na dysku)."""
    os.makedirs("Textures", exist_ok=True)
    cache_path = os.path.join("Textures", f"regolith_detail_{size}.npz")
    if os.path.exists(cache_path):
        data = np.load(cache_path)
        return data["albedo_mod"], data["bump_n"], data["bump_e"]

    u = np.linspace(0.0, 2.0 * math.pi, size, endpoint=False, dtype=np.float32)
    v = np.linspace(0.0, 2.0 * math.pi, size, endpoint=False, dtype=np.float32)
    gx, gy = np.meshgrid(u, v)

    h = (
        0.32 * np.sin(gx * 2.0 + 0.3) * np.cos(gy * 2.0 - 0.5)
        + 0.24 * np.sin(gx * 5.0 - gy * 4.0 + 1.1)
        + 0.17 * np.cos(gx * 11.0 + gy * 9.0 - 0.7)
        + 0.12 * np.sin(gx * 23.0 - gy * 19.0 + 0.4)
        + 0.08 * np.cos(gx * 47.0 + gy * 43.0)
        + 0.05 * np.sin(gx * 97.0 - gy * 89.0)
    )

    rng = np.random.default_rng(123)
    for _ in range(240):
        cx = rng.uniform(0.0, 2.0 * math.pi)
        cy = rng.uniform(0.0, 2.0 * math.pi)
        cr = rng.uniform(0.045, 0.22)
        dx = (gx - cx + math.pi) % (2.0 * math.pi) - math.pi
        dy = (gy - cy + math.pi) % (2.0 * math.pi) - math.pi
        d = np.sqrt(dx * dx + dy * dy)
        inside = d < cr
        rim = (d >= cr) & (d < cr * 1.28)
        h[inside] -= 0.48 * (1.0 - (d[inside] / cr) ** 2)
        h[rim] += 0.15 * np.sin((d[rim] - cr) / (0.28 * cr) * math.pi)

    bump_n = (np.gradient(h, axis=0) * 2.2).astype(np.float32)
    bump_e = (np.gradient(h, axis=1) * 2.2).astype(np.float32)
    albedo_mod = np.clip(1.0 + 0.24 * h, 0.62, 1.42).astype(np.float32)

    np.savez(cache_path, albedo_mod=albedo_mod, bump_n=bump_n, bump_e=bump_e)
    return albedo_mod, bump_n, bump_e


class LunarTerrain3D:
    """Pikselowy shader powierzchni Księżyca z gładką interpolacją, mikro-kraterami i 60 FPS."""

    LUT_SIZE = 4096

    def __init__(self, dem_km: np.ndarray, albedo_rgb: np.ndarray):
        self.dem = dem_km
        self.H, self.W = dem_km.shape
        self.albedo_map = albedo_rgb
        self.AH, self.AW = albedo_rgb.shape[:2]

        self.det_alb, self.det_bn, self.det_be = build_regolith_detail_tiles(512)

        self.n_r = 220
        self.n_az = 720
        self.az_grid = np.linspace(0.0, 2.0 * np.pi, self.n_az + 1, dtype=np.float32)
        self.radii_km = None

        self.max_r_km = 220.0
        self.inv_sqrt_scale = 1.0
        self.lut_idx_lo = None
        self.lut_wr = None
        self.lut_fade_fine = None
        self.lut_fade_med = None

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
        self.lut_fade_fine = np.exp(-r_lut / max(0.35, h_safe * 25.0)).astype(np.float32)
        self.lut_fade_med = np.exp(-r_lut / max(12.0, h_safe * 450.0)).astype(np.float32)

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
            0.032 * np.sin(lat_r * 920.0) * np.cos(lon_r * 920.0)
            + 0.014 * np.sin(lat_r * 2400.0 + 1.1) * np.sin(lon_r * 2400.0 - 0.7)
        )
        return (base_h + detail).astype(np.float32)

    def sample_albedo_bilinear(self, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
        fy = np.clip((90.0 - lat_deg) / 180.0 * (self.AH - 1), 0.0, self.AH - 1.0001)
        lon_wrapped = ((lon_deg + 180.0) % 360.0) - 180.0
        fx = (lon_wrapped + 180.0) / 360.0 * self.AW

        y0 = np.floor(fy).astype(np.int32)
        x0 = np.floor(fx).astype(np.int32) % self.AW
        y1 = np.minimum(y0 + 1, self.AH - 1)
        x1 = (x0 + 1) % self.AW

        wy = (fy - y0)[..., None]
        wx = (fx - np.floor(fx))[..., None]

        return (
            (self.albedo_map[y0, x0] * (1.0 - wx) + self.albedo_map[y0, x1] * wx) * (1.0 - wy)
            + (self.albedo_map[y1, x0] * (1.0 - wx) + self.albedo_map[y1, x1] * wx) * wy
        ).astype(np.float32)

    def update_observer(self, lat_deg: float, lon_deg: float, alt_above_surface_km: float = 0.002):
        state_key = (round(lat_deg, 5), round(lon_deg, 5), round(alt_above_surface_km, 6))
        if self.cached_state == state_key:
            return
        self.cached_state = state_key
        self.alt_above_km = alt_above_surface_km

        self._build_polar_and_lut(alt_above_surface_km)

        ground_h = float(self.sample_dem_bilinear(np.array([lat_deg]), np.array([lon_deg]))[0])
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

        h_grid = self.sample_dem_bilinear(v_lat, v_lon)
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

        self.alb_polar = self.sample_albedo_bilinear(v_lat, v_lon)

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
        scale_div = 2.6 if max(cw, ch) >= 1100 else 2.0
        rw = max(320, int(cw / scale_div))
        rh = max(200, int(ch / scale_div))

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

                R_obs = self.obs_radius_km
                b = R_obs * dz_v
                c0 = R_obs * R_obs - R_MOON * R_MOON
                disc = np.maximum(0.0, b * b - c0)
                t_hit = -b - np.sqrt(disc)

                hor_dist_v = self.hor_dist_az[az0_v] * (1.0 - waz_v) + self.hor_dist_az[az1_v] * waz_v
                horiz_speed = np.sqrt(np.maximum(1e-8, dx_v * dx_v + dy_v * dy_v))
                r_ground = np.clip(t_hit * horiz_speed, 0.0, hor_dist_v)

                lut_idx = np.minimum(self.LUT_SIZE - 1, (np.sqrt(r_ground) * self.inv_sqrt_scale).astype(np.int32))
                r0 = self.lut_idx_lo[lut_idx]
                r1 = np.minimum(r0 + 1, self.n_r - 1)
                wr = self.lut_wr[lut_idx]
                fade_fine = self.lut_fade_fine[lut_idx]
                fade_med = self.lut_fade_med[lut_idx]

                w00 = (1.0 - wr) * (1.0 - waz_v)
                w01 = (1.0 - wr) * waz_v
                w10 = wr * (1.0 - waz_v)
                w11 = wr * waz_v

                base_rgb = (
                    self.alb_polar[r0, az0_v] * w00[:, None]
                    + self.alb_polar[r0, az1_v] * w01[:, None]
                    + self.alb_polar[r1, az0_v] * w10[:, None]
                    + self.alb_polar[r1, az1_v] * w11[:, None]
                )
                n_vec = (
                    self.norm_polar[r0, az0_v] * w00[:, None]
                    + self.norm_polar[r0, az1_v] * w01[:, None]
                    + self.norm_polar[r1, az0_v] * w10[:, None]
                    + self.norm_polar[r1, az1_v] * w11[:, None]
                )

                inv_hs = r_ground / horiz_speed
                rel_n = dx_v * inv_hs
                rel_e = dy_v * inv_hs

                ix_fine = (rel_n * 2400.0).astype(np.int32) & 511
                iy_fine = (rel_e * 2400.0).astype(np.int32) & 511
                ix_med = (rel_n * 145.0).astype(np.int32) & 511
                iy_med = (rel_e * 145.0).astype(np.int32) & 511

                tex_mod = (
                    1.0
                    + (self.det_alb[ix_fine, iy_fine] - 1.0) * fade_fine
                    + (self.det_alb[ix_med, iy_med] - 1.0) * fade_med
                )
                n_vec[:, 0] += self.det_bn[ix_fine, iy_fine] * fade_fine + 0.65 * self.det_bn[ix_med, iy_med] * fade_med
                n_vec[:, 1] += self.det_be[ix_fine, iy_fine] * fade_fine + 0.65 * self.det_be[ix_med, iy_med] * fade_med
                n_vec /= np.maximum(np.linalg.norm(n_vec, axis=-1, keepdims=True), 1e-6)

                sun_enu = np.array([
                    math.cos(sun_alt) * math.cos(sun_az),
                    math.cos(sun_alt) * math.sin(sun_az),
                    math.sin(sun_alt),
                ], dtype=np.float32)
                sun_hor = self.get_horizon_at_azimuth(sun_az)
                sun_above = max(0.0, min(1.0, (sun_alt - (sun_hor - math.radians(0.35))) / math.radians(0.60)))

                ndotl = np.maximum(0.0, n_vec @ sun_enu)
                lunar_reflectance = (ndotl / (ndotl + 0.16)) * 1.16 * sun_above
                earthshine = 0.045 * max(0.0, math.sin(earth_alt))
                ambient = 0.032 + earthshine

                intensity = (165.0 * ambient + 940.0 * lunar_reflectance) * tex_mod
                rgb_out = np.clip(base_rgb * intensity[:, None], 6, 248).astype(np.uint8)

                out_rgba = np.zeros((rh, rw, 4), dtype=np.uint8)
                sub_out = out_rgba[y_start:]
                sub_out[valid, :3] = rgb_out
                sub_out[valid, 3] = (edge_alpha[valid] * 255.0).astype(np.uint8)

                surf = pygame.image.frombuffer(out_rgba.tobytes(), (rw, rh), "RGBA")
                surf_full = pygame.transform.smoothscale(surf, (cw, ch))
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


def draw_telescopic_earth(screen, ex, ey, r_earth_exact, cw, ch, sun_earth_dir, spin_angle,
                          day_arr=None, night_arr=None, clouds_arr=None):
    """Wektorowy renderer tarczy Ziemi 3D skalujący się prawidłowo przy każdym przybliżeniu."""
    r_earth = max(4.0, r_earth_exact)
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

    xs = (np.linspace(x0, x1 - 1, max(2, w_box // ss), dtype=np.float32) - ex) / r_earth
    ys = (np.linspace(y0, y1 - 1, max(2, h_box // ss), dtype=np.float32) - ey) / r_earth
    gx, gy = np.meshgrid(xs, ys)
    dist_sq = gx * gx + gy * gy
    mask = dist_sq <= 1.0
    if not np.any(mask):
        return

    gz = np.zeros_like(dist_sq)
    gz[mask] = np.sqrt(1.0 - dist_sq[mask])

    px = gz[mask]
    py = -gx[mask]
    pz = -gy[mask]

    lat_pt = np.arcsin(np.clip(pz, -1.0, 1.0))
    lon_pt = (np.arctan2(py, px) + spin_angle + np.pi) % (2.0 * np.pi) - np.pi

    u = (lon_pt + np.pi) / (2.0 * np.pi)
    v = (np.pi * 0.5 - lat_pt) / np.pi

    if day_arr is not None:
        dh, dw = day_arr.shape[:2]
        tx = (u * dw).astype(np.int32) % dw
        ty = (v * dh).astype(np.int32) % dh
        rgb = day_arr[ty, tx].astype(np.float32)
    else:
        continent = (
            np.sin(lon_pt * 2.1 + 0.4) * np.cos(lat_pt * 2.3)
            + 0.55 * np.cos(lon_pt * 4.7 - 1.1) * np.sin(lat_pt * 3.8 + 0.3)
            + 0.30 * np.sin(lon_pt * 9.0 + lat_pt * 7.0)
        )
        is_land = continent > 0.18
        is_ice = np.abs(lat_pt) > np.radians(72.0 - 8.0 * continent)
        rgb = np.empty((px.shape[0], 3), dtype=np.float32)
        rgb[:] = (22.0, 72.0, 158.0)
        rgb[is_land] = (64.0, 118.0, 62.0)
        rgb[is_ice] = (235.0, 242.0, 248.0)

    cos_sun = px * sun_earth_dir[0] + py * sun_earth_dir[1] + pz * sun_earth_dir[2]
    day_side = cos_sun > 0.0

    out_rgb = np.zeros_like(rgb)
    if np.any(day_side):
        if clouds_arr is not None:
            ch_t, cw_t = clouds_arr.shape[:2]
            cx = (u[day_side] * cw_t).astype(np.int32) % cw_t
            cy = (v[day_side] * ch_t).astype(np.int32) % ch_t
            cf = (clouds_arr[cy, cx, 0].astype(np.float32) / 255.0) * 0.75
            rgb[day_side] = rgb[day_side] * (1.0 - cf[:, None]) + 255.0 * cf[:, None]
        factor = np.clip(cos_sun[day_side], 0.12, 1.0)[:, None]
        out_rgb[day_side] = rgb[day_side] * factor

    if np.any(~day_side):
        n_idx = ~day_side
        if night_arr is not None:
            nh, nw = night_arr.shape[:2]
            nx = (u[n_idx] * nw).astype(np.int32) % nw
            ny = (v[n_idx] * nh).astype(np.int32) % nh
            out_rgb[n_idx] = night_arr[ny, nx].astype(np.float32)
        else:
            out_rgb[n_idx] = rgb[n_idx] * 0.05

    limb = np.power(1.0 - gz[mask], 3.0) * np.clip(cos_sun + 0.25, 0.0, 1.0)
    out_rgb[:, 0] += 70.0 * limb
    out_rgb[:, 1] += 140.0 * limb
    out_rgb[:, 2] += 235.0 * limb

    img = np.zeros((ys.shape[0], xs.shape[0], 4), dtype=np.uint8)
    img[mask, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    img[mask, 3] = 255

    surf = pygame.image.frombuffer(img.tobytes(), (xs.shape[0], ys.shape[0]), "RGBA")
    if ss > 1:
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
        mean_moon_dist = float(np.mean(np.linalg.norm(coords[:, 3:6], axis=1)))
        if mean_moon_dist > 1e7:
            coords *= 0.001
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

    sun_earth_body = sun_body - earth_body
    sun_earth_dir = sun_earth_body / np.linalg.norm(sun_earth_body)

    current_time = times[idx0] + (times[idx1] - times[idx0]) * frac
    return {
        "time": current_time,
        "d_j2000": d_j2000,
        "R_body": R_body,
        "earth": (earth_alt, earth_az, earth_dist),
        "sun": (sun_alt, sun_az, sun_dist),
        "obs_bases": (north, east, up),
        "sun_earth_dir": sun_earth_dir,
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
    pygame.display.set_caption("Lunar Stellarium - Gładka Tekstura Powierzchni Księżyca")
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
            earth_spin = (2.0 * math.pi * d_j2000 * 1.0027379) % (2.0 * math.pi)
            draw_telescopic_earth(
                screen, ex, ey, r_earth_exact, cw, ch,
                sun_earth_dir, earth_spin,
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
            "[M] Siatka 3D | [H] Linia horyzontu | [1-5] Lokacje Księżyca",
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