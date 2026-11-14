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

I_MOON = math.radians(1.5424)      # Nachylenie równika księżycowego do ekliptyki
OBLIQUITY = math.radians(23.4393)  # Nachylenie osi Ziemi do ekliptyki (J2000)
SIDEREAL_MONTH = 27.321661         # dni
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


def load_earth_textures():
    """Wczytuje tekstury Ziemi (dzień, noc, chmury) z folderu Textures/."""
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

    night_candidates = [
        "Textures/earth_night8K.jpg",
        "Textures/earth_night8K.png",
        "Textures/earth_night.jpg",
        "Textures/earth_night.png",
    ]
    night_path = next((p for p in night_candidates if os.path.exists(p)), None)

    clouds_candidates = [
        "Textures/earth_clouds8K.jpg",
        "Textures/earth_clouds8K.png",
        "Textures/earth_clouds.jpg",
        "Textures/earth_clouds.png",
    ]
    clouds_path = next((p for p in clouds_candidates if os.path.exists(p)), None)

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
    """Model 3D powierzchni Księżyca z teksturą regolitu i profilem horyzontu."""

    def __init__(self, dem_km: np.ndarray, albedo_rgb: np.ndarray):
        self.dem = dem_km
        self.H, self.W = dem_km.shape
        self.albedo_map = albedo_rgb
        self.AH, self.AW = albedo_rgb.shape[:2]

        self.radii_km = np.concatenate(([0.0], np.geomspace(0.0005, 450.0, 72)))
        self.az_grid = np.linspace(0.0, 2.0 * np.pi, 481)
        self.n_r = len(self.radii_km)
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
            0.035 * np.sin(lat_r * 950.0) * np.cos(lon_r * 950.0)
            + 0.015 * np.sin(lat_r * 2600.0 + 1.1) * np.sin(lon_r * 2600.0 - 0.7)
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

        delta = (self.radii_km / R_MOON)[:, None]
        az = self.az_grid[None, :]

        u_body = (
            np.cos(delta)[..., None] * up0[None, None, :]
            + (np.sin(delta) * np.cos(az))[..., None] * north0[None, None, :]
            + (np.sin(delta) * np.sin(az))[..., None] * east0[None, None, :]
        )

        v_lat = np.degrees(np.arcsin(np.clip(u_body[..., 2], -1.0, 1.0)))
        v_lon = np.degrees(np.arctan2(u_body[..., 1], u_body[..., 0]))

        h_grid = self.sample_dem_bilinear(v_lat, v_lon)
        r_grid = R_MOON + h_grid

        p_body = r_grid[..., None] * u_body
        obs_body = self.obs_radius_km * up0
        rel_body = p_body - obs_body[None, None, :]

        rel_n = rel_body @ north0
        rel_e = rel_body @ east0
        rel_u = rel_body @ up0
        self.pts_enu = np.stack([rel_n, rel_e, rel_u], axis=-1)

        p00 = self.pts_enu[:-1, :-1]
        p10 = self.pts_enu[1:, :-1]
        p01 = self.pts_enu[:-1, 1:]
        p11 = self.pts_enu[1:, 1:]
        normals = np.cross(p10 - p00, p01 - p00)
        normals[0] = np.cross(p10[0] - p00[0], p11[0] - p00[0])
        norms = np.linalg.norm(normals, axis=-1, keepdims=True)
        normals = normals / np.maximum(norms, 1e-15)

        mid_n = 0.25 * (rel_n[:-1, :-1] + rel_n[1:, :-1] + rel_n[:-1, 1:] + rel_n[1:, 1:])
        mid_e = 0.25 * (rel_e[:-1, :-1] + rel_e[1:, :-1] + rel_e[:-1, 1:] + rel_e[1:, 1:])
        mid_lat = 0.25 * (v_lat[:-1, :-1] + v_lat[1:, :-1] + v_lat[:-1, 1:] + v_lat[1:, 1:])
        mid_lon = 0.25 * (v_lon[:-1, :-1] + v_lon[1:, :-1] + v_lon[:-1, 1:] + v_lon[1:, 1:])

        bump_n = 0.04 * np.sin(mid_n * 55.0 - mid_e * 37.0)
        bump_e = 0.04 * np.cos(mid_n * 43.0 + mid_e * 61.0)
        normals[..., 0] += bump_n
        normals[..., 1] += bump_e
        normals /= np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-15)
        self.normals_enu = normals

        self.quad_rgb = self.sample_surface_texture(mid_lat, mid_lon, mid_n, mid_e)

        dist_3d = np.linalg.norm(self.pts_enu[1:], axis=-1)
        elev_angles = np.arcsin(np.clip(rel_u[1:] / np.maximum(dist_3d, 1e-9), -1.0, 1.0))
        hor_idx = np.argmax(elev_angles, axis=0)
        az_indices = np.arange(elev_angles.shape[1])

        self.horizon_alt = elev_angles[hor_idx, az_indices]
        self.horizon_dist_km = dist_3d[hor_idx, az_indices]
        self.horizon_lat = v_lat[1:][hor_idx, az_indices]
        self.horizon_lon = v_lon[1:][hor_idx, az_indices]
        self.horizon_elev_km = h_grid[1:][hor_idx, az_indices]

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
                wireframe=False, show_horizon_line=True):
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

        z_cam = self.pts_enu @ fwd
        x_cam = self.pts_enu @ right
        y_cam = self.pts_enu @ cam_up

        near_z = 0.0001
        focal = (ch / 2.0) / math.tan(fov / 2.0)
        safe_z = np.where(z_cam > near_z, z_cam, near_z)
        sx = np.clip(cw / 2.0 + (x_cam / safe_z) * focal, -16000.0, 16000.0)
        sy = np.clip(ch / 2.0 - (y_cam / safe_z) * focal, -16000.0, 16000.0)

        sun_enu = np.array([
            math.cos(sun_alt) * math.cos(sun_az),
            math.cos(sun_alt) * math.sin(sun_az),
            math.sin(sun_alt),
        ])
        ndotl = np.einsum("ijk,k->ij", self.normals_enu, sun_enu)
        direct = np.power(np.maximum(0.0, ndotl), 0.85)
        earthshine = 0.045 * max(0.0, math.sin(earth_alt))
        ambient = 0.032 + earthshine

        light_intensity = (165.0 * ambient + 940.0 * direct)[..., None]
        lit_rgb = np.clip(self.quad_rgb * light_intensity, 6, 248).astype(np.uint8)

        for i in range(self.n_r - 2, -1, -1):
            z00, z10 = z_cam[i, :-1], z_cam[i + 1, :-1]
            z11, z01 = z_cam[i + 1, 1:], z_cam[i, 1:]
            in_front = (z00 > near_z) & (z10 > near_z) & (z11 > near_z) & (z01 > near_z)
            if not np.any(in_front):
                continue

            x00, y00 = sx[i, :-1], sy[i, :-1]
            x10, y10 = sx[i + 1, :-1], sy[i + 1, :-1]
            x11, y11 = sx[i + 1, 1:], sy[i + 1, 1:]
            x01, y01 = sx[i, 1:], sy[i, 1:]

            min_x = np.minimum(np.minimum(x00, x10), np.minimum(x11, x01))
            max_x = np.maximum(np.maximum(x00, x10), np.maximum(x11, x01))
            min_y = np.minimum(np.minimum(y00, y10), np.minimum(y11, y01))
            max_y = np.maximum(np.maximum(y00, y10), np.maximum(y11, y01))

            visible = in_front & (max_x >= -80) & (min_x <= cw + 80) & (max_y >= -80) & (min_y <= ch + 80)
            vis_idx = np.nonzero(visible)[0]
            row_col = lit_rgb[i]

            for j in vis_idx:
                poly = [
                    (int(x00[j]), int(y00[j])),
                    (int(x10[j]), int(y10[j])),
                    (int(x11[j]), int(y11[j])),
                    (int(x01[j]), int(y01[j])),
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
                          ecef_axes_enu, cloud_time,
                          day_arr=None, night_arr=None, clouds_arr=None):
    """Wektorowy renderer tarczy Ziemi 3D z dokładną fazą, teksturą dnia/nocy i ruchem chmur."""
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

    # Baza ekranowa tarczy Ziemi w układzie ENU obserwatora:
    # e_z_cam: od środka Ziemi w stronę obserwatora (+gz)
    # e_x_cam: w prawo na ekranie (+gx)
    # e_y_cam: w górę na ekranie (-gy)
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

    # Próbkowanie tekstury dziennej
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

    # Próbkowanie tekstury nocnej (światła miast)
    if night_arr is not None:
        nh, nw = night_arr.shape[:2]
        nx = (u * nw).astype(np.int32) % nw
        ny = np.clip((v * nh).astype(np.int32), 0, nh - 1)
        night_rgb = night_arr[ny, nx].astype(np.float32) * 1.15
    else:
        night_rgb = day_rgb * 0.06

    # Kosinus kąta padania promieni słonecznych (faza Ziemi)
    cos_sun = n_enu @ sun_from_earth_enu

    # Płynna funkcja przejścia przez terminator (-0.10 .. +0.08)
    twilight_t = np.clip((cos_sun + 0.10) / 0.18, 0.0, 1.0)
    day_blend = twilight_t * twilight_t * (3.0 - 2.0 * twilight_t)

    # Cieniowanie strony dziennej + ciepły odcień zachodu/wschodu słońca przy terminatorze
    sun_diffuse = np.power(np.clip(cos_sun, 0.0, 1.0), 0.78)
    terminator_glow = np.exp(-((cos_sun - 0.02) / 0.11) ** 2) * (cos_sun > -0.10)

    lit_day_rgb = day_rgb * (0.08 + 0.96 * sun_diffuse)[:, None]
    lit_day_rgb[:, 0] += 42.0 * terminator_glow
    lit_day_rgb[:, 1] += 14.0 * terminator_glow

    # Animacja chmur względem powierzchni Ziemi (pasaty, prądy strumieniowe i fale Rossby'ego)
    cloud_alpha = None
    if clouds_arr is not None:
        ch_t, cw_t = clouds_arr.shape[:2]

        # Warstwa 1: główny system chmur z wiatrem strefowym (trade winds & westerlies) + falą
        zonal_shear_1 = cloud_time * (0.016 * np.cos(3.0 * lat_pt) - 0.007 * np.cos(lat_pt))
        meridional_wave_1 = 0.0055 * np.sin(lon_pt * 3.0 + cloud_time * 0.42) * np.cos(lat_pt)
        u_c1 = (u + zonal_shear_1) % 1.0
        v_c1 = np.clip(v + meridional_wave_1, 0.0, 0.9999)
        cx1 = (u_c1 * cw_t).astype(np.int32) % cw_t
        cy1 = (v_c1 * ch_t).astype(np.int32)
        c1 = clouds_arr[cy1, cx1, 0].astype(np.float32) / 255.0

        # Warstwa 2: wysokie chmury cirrus w prądach strumieniowych (efekt głębi i paralaksy)
        zonal_shear_2 = cloud_time * (0.028 * (np.sin(2.0 * lat_pt) ** 2) + 0.009) + 0.37
        meridional_wave_2 = -0.0045 * np.cos(lon_pt * 4.0 - cloud_time * 0.58) * np.cos(lat_pt) + 0.11
        u_c2 = (u + zonal_shear_2) % 1.0
        v_c2 = np.clip(v + meridional_wave_2, 0.0, 0.9999)
        cx2 = (u_c2 * cw_t).astype(np.int32) % cw_t
        cy2 = (v_c2 * ch_t).astype(np.int32)
        c2 = clouds_arr[cy2, cx2, 0].astype(np.float32) / 255.0

        cloud_alpha = np.clip(c1 * 0.82 + c2 * 0.30, 0.0, 0.95)

        # Na oświetlonej części chmury są jasne i odbijają światło słoneczne oraz złoty blask terminatora
        cloud_lit_r = 252.0 * (0.10 + 0.94 * sun_diffuse) + 55.0 * terminator_glow
        cloud_lit_g = 253.0 * (0.10 + 0.94 * sun_diffuse) + 20.0 * terminator_glow
        cloud_lit_b = 255.0 * (0.11 + 0.93 * sun_diffuse)
        cloud_lit_rgb = np.stack([cloud_lit_r, cloud_lit_g, cloud_lit_b], axis=-1)

        cf_day = cloud_alpha[:, None]
        lit_day_rgb = lit_day_rgb * (1.0 - cf_day) + cloud_lit_rgb * cf_day

        # Na ciemnej części chmury delikatnie przesłaniają światła miast pod nimi
        night_rgb = night_rgb * (1.0 - 0.55 * cloud_alpha)[:, None]

    # Połączenie strony nocnej i oświetlonej
    out_rgb = night_rgb * (1.0 - day_blend)[:, None] + lit_day_rgb * day_blend[:, None]

    # Rozpraszanie Rayleigha na krawędzi atmosfery Ziemi (tylko po stronie oświetlonej / zmierzchowej)
    limb = np.power(1.0 - gz[mask], 2.6) * np.clip(cos_sun + 0.28, 0.0, 1.0)
    out_rgb[:, 0] += 75.0 * limb
    out_rgb[:, 1] += 155.0 * limb
    out_rgb[:, 2] += 250.0 * limb

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
        sun_facing = np.clip((n_halo @ sun_from_earth_enu) + 0.32, 0.06, 1.0)
        img[halo_mask, 0] = 75
        img[halo_mask, 1] = 155
        img[halo_mask, 2] = 250
        img[halo_mask, 3] = np.clip(155.0 * h_fade * sun_facing, 0, 255).astype(np.uint8)

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

    def ecl_to_enu(v_ecl):
        v_b = R_body @ v_ecl
        return np.array([v_b @ north, v_b @ east, v_b @ up])

    # Kierunek od środka Ziemi do Słońca w układzie ENU obserwatora
    sun_from_earth_ecl = sun_geo / np.linalg.norm(sun_geo)
    sun_from_earth_enu = ecl_to_enu(sun_from_earth_ecl)

    # Baza geograficzna Ziemi (ECEF) w układzie ENU obserwatora (z nachyleniem osi 23.44° i czasem GMST)
    x_eci_ecl = np.array([1.0, 0.0, 0.0])
    y_eci_ecl = np.array([0.0, math.cos(OBLIQUITY), -math.sin(OBLIQUITY)])
    z_eci_ecl = np.array([0.0, math.sin(OBLIQUITY), math.cos(OBLIQUITY)])

    gmst = math.radians((280.46061837 + 360.98564736629 * d_j2000) % 360.0)
    cg, sg = math.cos(gmst), math.sin(gmst)

    x_ecef_ecl = cg * x_eci_ecl + sg * y_eci_ecl
    y_ecef_ecl = -sg * x_eci_ecl + cg * y_eci_ecl
    z_ecef_ecl = z_eci_ecl

    ecef_axes_enu = (
        ecl_to_enu(x_ecef_ecl),
        ecl_to_enu(y_ecef_ecl),
        ecl_to_enu(z_ecef_ecl),
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

    earth_day_arr, earth_night_arr, earth_clouds_arr = load_earth_textures()

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
            - (math.atan2(dx_px, focal_old) - math.atan2(dx_px, focal_new)) / max(0.25, math.cos(cam_alt))
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
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(fwd, world_up)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([-math.sin(cam_az), math.cos(cam_az), 0.0])
        else:
            right /= np.linalg.norm(right)
        cam_up = np.cross(right, fwd)
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
                    dist_ang = math.hypot(cam_alt - data["earth"][0], (cam_az - data["earth"][1] + math.pi) % (2 * math.pi) - math.pi)
                    cam_alt, cam_az = data["earth"][0], data["earth"][1]
                    if dist_ang < math.radians(2.0):
                        target_fov = math.radians(3.2)
                elif event.key == pygame.K_s:
                    dist_ang = math.hypot(cam_alt - data["sun"][0], (cam_az - data["sun"][1] + math.pi) % (2 * math.pi) - math.pi)
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
        ecef_axes_enu = data["ecef_axes_enu"]
        d_j2000 = data["d_j2000"]

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
            ang_sun = math.asin(min(1.0, R_SUN / sun_dist))
            r_sun_exact = math.tan(ang_sun) * focal / z_cam
            draw_telescopic_sun(screen, sx, sy, r_sun_exact, cw, ch)
            r_label = max(6, int(r_sun_exact))
            if 0 <= sx + r_label + 6 < cw and 0 <= sy - 8 < ch:
                screen.blit(font.render("Słońce", True, (255, 230, 150)), (sx + r_label + 6, sy - 8))

        # 4. ZIEMIA (wektorowy renderer 3D z dokładną fazą, teksturą dnia/nocy i ruchem chmur)
        earth_proj = project_point(earth_alt, earth_az, cw, ch, cam_basis)
        if earth_proj:
            ex, ey, z_cam, focal = earth_proj
            ang_earth = math.asin(min(1.0, R_EARTH / earth_dist))
            r_earth_exact = math.tan(ang_earth) * focal / z_cam
            dir_earth_enu = np.array([
                math.cos(earth_alt) * math.cos(earth_az),
                math.cos(earth_alt) * math.sin(earth_az),
                math.sin(earth_alt),
            ])
            cloud_time = d_j2000 * 5.0 + anim_time * 0.35
            draw_telescopic_earth(
                screen, ex, ey, r_earth_exact, cw, ch,
                cam_right, cam_up, dir_earth_enu, sun_from_earth_enu,
                ecef_axes_enu, cloud_time,
                day_arr=earth_day_arr,
                night_arr=earth_night_arr,
                clouds_arr=earth_clouds_arr,
            )
            r_elabel = max(8, int(r_earth_exact))
            if 0 <= ex + r_elabel + 8 < cw and 0 <= ey - 8 < ch:
                screen.blit(font.render("Ziemia", True, (130, 200, 255)), (ex + r_elabel + 8, ey - 8))

        # 5. MODEL 3D TEKSTUROWANEJ POWIERZCHNI KSIĘŻYCA I HORYZONTU
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
            proj = project_point(h_alt, az_r, cw, ch, cam_basis)
            if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                col = (255, 90, 90) if label == "N" else (210, 220, 235)
                txt = font_big.render(label, True, col)
                screen.blit(txt, (proj[0] - txt.get_width() // 2, proj[1] - txt.get_height() // 2))

        # 7. HUD
        earth_hor = terrain_3d.get_horizon_at_azimuth(earth_az)
        sun_hor = terrain_3d.get_horizon_at_azimuth(sun_az)
        cam_hor = terrain_3d.get_horizon_at_azimuth(cam_az)
        zoom_mag = base_fov / fov
        height_str = format_height_m(slider_height.val)

        earth_vis = "WIDOCZNA" if earth_alt > earth_hor else "ZA HORYZONTEM"
        sun_vis = "WIDOCZNE" if sun_alt > sun_hor else "ZA HORYZONTEM"

        info_lines = [
            f"Lokacja: {location_name} | DEM: {dem_source}",
            f"Teren: {terrain_3d.obs_elev_km:+.3f} km | Wys. obs.: {height_str} | Zoom: {zoom_mag:.1f}x",
            f"Kamera: Az {math.degrees(cam_az):.2f}° | Alt {math.degrees(cam_alt):+.2f}° (Hor: {math.degrees(cam_hor):+.2f}°)",
            "-" * 58,
            f"ZIEMIA: Alt {math.degrees(earth_alt):+6.2f}° | Az {math.degrees(earth_az):6.2f}° [{earth_vis}]",
            f"SŁOŃCE: Alt {math.degrees(sun_alt):+6.2f}° | Az {math.degrees(sun_az):6.2f}° [{sun_vis}]",
            "-" * 58,
            "[Scroll / +/-] Zoom (do 375x) | [R] Reset zoomu | [Spacja] Play",
            "[E] Ziemia (2x = zoom) | [S] Słońce (2x = zoom) | [L] Horyzont",
            "[M] Siatka 3D | [H] Linia horyzontu | [C] Zapisz horizon.csv",
            "[1-5] Lokacje Księżyca",
        ]

        panel_w = 595
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
