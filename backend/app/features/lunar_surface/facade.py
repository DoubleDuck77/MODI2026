"""Fasada ``lunar_surface``: cienki adapter na ``newlunar.py`` (tylko import, bez zmian).

Teren: jedna instancja ``newlunar.LunarTerrain3D`` z mapami v3 (tę gałąź wybiera
``load_or_download_lunar_maps`` przy obecnych plikach, ``newlunar.py:153-160``). Instancja ma stan
(okno siatki, profil horyzontu bieżącego obserwatora), więc każde użycie jest pod jednym lockiem.

Niebo: ``newlunar.get_topocentric_vectors`` + wzory pętli głównej ``newlunar.py:1960-1992``
i statusy HUD ``newlunar.py:2081-2091``.
"""

import base64
import math
import threading

import numpy as np
from fastapi import HTTPException

from app.core.contracts import CONTRACT_VERSION, ReferenceFrame, ResponseMeta, SelenoPoint
from app.core.facade import BaseFacade
from app.core.legacy import import_root_script
from app.features.lunar_surface.contract import (
    EarthInSky,
    HorizonProfile,
    LunarSky,
    LunarTerrainPatch,
    SunInSky,
    SurfaceQuery,
    TerrainQuery,
)
from app.features.lunar_surface.year_data import load_year, time_index

DEM_FILE = "moon_dem_nasa_16ppd_v3.npy"
COLOR_FILE = "moon_color_nasa_8k_v3.npy"
DEM_SOURCE = "NASA LOLA 16 px/deg"  # ten sam opis co newlunar.py:160


def _vec(v) -> tuple:
    return (float(v[0]), float(v[1]), float(v[2]))


def _b64(a: np.ndarray, dtype: str) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode("ascii")


class LunarSurfaceFacade(BaseFacade):
    feature_id = "lunar_surface"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.nl = import_root_script("newlunar", ctx.settings.scripts_dir)
        self._lock = threading.Lock()
        self._terrain_obj = None

    # --- pomocnicze ----------------------------------------------------------------------

    def _meta(self, endpoint: str) -> ResponseMeta:
        return ResponseMeta(
            feature=self.feature_id, endpoint=endpoint, contract_version=CONTRACT_VERSION,
            source="computed", frame=ReferenceFrame.TOPOCENTRIC_HORIZON,
            units={"angle": "deg", "distance": "km", "elevation": "m"},
        )

    def _terrain(self):
        """Leniwie tworzy ``LunarTerrain3D`` (wywoływać pod ``self._lock``)."""
        if self._terrain_obj is None:
            tex = self.ctx.settings.textures_dir
            dem_path, color_path = tex / DEM_FILE, tex / COLOR_FILE
            if not (dem_path.is_file() and color_path.is_file()):
                raise HTTPException(503, f"Brak map terenu v3 ({DEM_FILE}, {COLOR_FILE}) w {tex}")
            dem = np.load(dem_path, mmap_mode="r")
            color = np.load(color_path, mmap_mode="r")
            self._terrain_obj = self.nl.LunarTerrain3D(dem, color)
        return self._terrain_obj

    # --- endpointy -----------------------------------------------------------------------

    def sky(self, q: SurfaceQuery) -> LunarSky:
        nl = self.nl
        year, idx = time_index(q.t)
        year_data = load_year(self.ctx.settings.coords_dir, year, nl.J2000)
        idx = min(idx, len(year_data["times"]) - 1)

        with self._lock:
            terrain = self._terrain()
            terrain.update_observer(q.lat_deg, q.lon_deg, eye_height_m=q.eye_height_m)
            data = nl.get_topocentric_vectors(
                year_data, idx, q.lat_deg, q.lon_deg, obs_radius_km=terrain.obs_radius_km
            )
            earth_alt, earth_az, earth_dist = data["earth"]
            sun_alt, sun_az, sun_dist = data["sun"]
            earth_hor = terrain.get_horizon_at_azimuth(earth_az)
            sun_hor = terrain.get_horizon_at_azimuth(sun_az)
            obs_elev_km = terrain.obs_elev_km
            obs_radius_km = terrain.obs_radius_km

        # --- newlunar.py:1965-1992 ---
        ang_earth = math.asin(min(1.0, nl.R_EARTH / earth_dist))
        ang_sun = math.asin(min(1.0, nl.R_SUN / sun_dist))
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
        sun_horizon_vis = nl.horizon_visible_fraction(sun_alt, sun_hor, ang_sun)
        if earth_dist < sun_dist:
            sep_earth_sun = math.acos(max(-1.0, min(1.0, float(np.dot(dir_earth_enu, dir_sun_enu)))))
            sun_eclipse_occ = nl.circle_overlap_fraction(ang_sun, ang_earth, sep_earth_sun)
            eclipse_ring_factor = max(0.0, min(1.0, 1.0 - max(0.0, sep_earth_sun - ang_earth) / (2.2 * ang_sun)))
            eclipse_ring_factor = eclipse_ring_factor * eclipse_ring_factor * (3.0 - 2.0 * eclipse_ring_factor)
        else:
            sun_eclipse_occ = 0.0
            eclipse_ring_factor = 0.0
        sun_eclipse_vis = 1.0 - sun_eclipse_occ
        sun_effective_vis = sun_horizon_vis * sun_eclipse_vis
        eclipse_red_glow = sun_horizon_vis * sun_eclipse_occ
        dark_side_exposure = 0.85 + 0.35 * (1.0 - sun_effective_vis)

        # --- statusy HUD, newlunar.py:2081-2091 ---
        earth_visible = earth_alt + ang_earth > earth_hor
        earth_vis = "WIDOCZNA" if earth_visible else "POD HORYZONTEM"
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

        north, east, up = data["obs_bases"]
        ecl_to_enu = np.stack([north, east, up]) @ data["R_body"]
        deg = math.degrees
        return LunarSky(
            meta=self._meta("sky"),
            t=q.t,
            observer=SelenoPoint(lat_deg=q.lat_deg, lon_deg=q.lon_deg),
            eye_height_m=q.eye_height_m,
            observer_elevation_m=obs_elev_km * 1000.0,
            observer_radius_km=obs_radius_km,
            earth=EarthInSky(
                alt_deg=deg(earth_alt), az_deg=deg(earth_az), distance_km=earth_dist,
                angular_radius_deg=deg(ang_earth), horizon_alt_deg=deg(earth_hor), dir_enu=_vec(dir_earth_enu),
                visible=earth_visible, status=earth_vis,
            ),
            sun=SunInSky(
                alt_deg=deg(sun_alt), az_deg=deg(sun_az), distance_km=sun_dist,
                angular_radius_deg=deg(ang_sun), horizon_alt_deg=deg(sun_hor), dir_enu=_vec(dir_sun_enu),
                horizon_visible_fraction=sun_horizon_vis, eclipse_occultation=sun_eclipse_occ,
                effective_visibility=sun_effective_vis, status=sun_vis,
            ),
            eclipse_ring_factor=eclipse_ring_factor,
            eclipse_red_glow=eclipse_red_glow,
            dark_side_exposure=dark_side_exposure,
            sun_from_earth_enu=_vec(data["sun_from_earth_enu"]),
            moon_from_earth_enu_km=_vec(data["moon_from_earth_enu"]),
            earth_axes_enu=tuple(_vec(a) for a in data["ecef_axes_enu"]),
            ecliptic_to_enu=tuple(_vec(row) for row in ecl_to_enu),
        )

    def terrain(self, q: TerrainQuery) -> LunarTerrainPatch:
        with self._lock:
            terrain = self._terrain()
            terrain.update_observer(q.lat_deg, q.lon_deg, eye_height_m=q.eye_height_m)

            # Siatka biegunowa — te same próbki co profil horyzontu w update_observer
            # (newlunar.py:768-778): 480 promieni geometrycznie od 15 m do r_max × 720 azymutów.
            up0, north0, east0 = terrain.up0, terrain.north0, terrain.east0
            hor_radii_km = np.geomspace(0.015, terrain.r_max_km, terrain.N_HOR_RAYS)
            az = terrain.az_grid[:-1]
            delta_h = (hor_radii_km / self.nl.R_MOON)[:, None]
            az_h = az[None, :]
            u_hor = (
                np.cos(delta_h)[..., None] * up0[None, None, :]
                + (np.sin(delta_h) * np.cos(az_h))[..., None] * north0[None, None, :]
                + (np.sin(delta_h) * np.sin(az_h))[..., None] * east0[None, None, :]
            )
            h_lat = np.degrees(np.arcsin(np.clip(u_hor[..., 2], -1.0, 1.0)))
            h_lon = np.degrees(np.arctan2(u_hor[..., 1], u_hor[..., 0]))
            h_elev = terrain.sample_window_mesh(h_lat, h_lon)

            # Albedo: najbliższy piksel mapy koloru 8K (średnia RGB, surowe 0–255).
            AH, AW = terrain.AH, terrain.AW
            py = np.clip(np.floor((90.0 - h_lat) / 180.0 * AH).astype(np.int64), 0, AH - 1)
            px = np.floor((h_lon + 180.0) / 360.0 * AW).astype(np.int64) % AW
            albedo = np.asarray(terrain.albedo_map[py, px], dtype=np.float32).mean(axis=-1)
            albedo = np.clip(np.rint(albedo), 0, 255).astype(np.uint8)

            n_az = terrain.n_az
            horizon = HorizonProfile(
                az_deg=np.degrees(terrain.az_grid[:n_az]).tolist(),
                alt_deg=np.degrees(terrain.horizon_alt[:n_az]).tolist(),
                distance_km=np.asarray(terrain.horizon_dist_km[:n_az], dtype=float).tolist(),
                lat_deg=np.asarray(terrain.horizon_lat[:n_az], dtype=float).tolist(),
                lon_deg=np.asarray(terrain.horizon_lon[:n_az], dtype=float).tolist(),
                elevation_km=np.asarray(terrain.horizon_elev_km[:n_az], dtype=float).tolist(),
            )
            out = dict(
                observer_elevation_m=terrain.obs_elev_km * 1000.0,
                observer_radius_km=terrain.obs_radius_km,
                r_max_km=terrain.r_max_km,
                window_sub=int(terrain.win.get("sub", 1)) if terrain.win else 1,
            )

        return LunarTerrainPatch(
            meta=self._meta("terrain"),
            observer=SelenoPoint(lat_deg=q.lat_deg, lon_deg=q.lon_deg),
            eye_height_m=q.eye_height_m,
            dem_source=DEM_SOURCE,
            n_az=int(n_az),
            n_r=int(len(hor_radii_km)),
            az_step_deg=360.0 / n_az,
            radii_km=hor_radii_km.tolist(),
            height_km_f32_b64=_b64(h_elev, "<f4"),
            albedo_u8_b64=_b64(albedo, "u1"),
            horizon=horizon,
            **out,
        )
