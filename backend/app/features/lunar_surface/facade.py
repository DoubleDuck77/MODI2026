"""Fasada ``lunar_surface``: cienki adapter na ``geografia.py`` (tylko import, bez zmian).

Teren: jedna bazowa instancja ``geografia.LunarTerrain3D`` z mapami v3 (tę gałąź wybiera
``load_or_download_lunar_maps``, ``geografia.py:358-365``), tworzona leniwie bez ``gl``. Rysuje
przeglądarka (WebGL2); serwer liczy tylko geometrię obserwatora (grunt, nachylenie, horyzont),
niebo i serwuje kafle DEM/albedo.

Wątki: ``update_observer`` i metody, które woła (``geografia.py:1734-1956``), jedynie
przypisują atrybuty (nie piszą w miejscu do współdzielonych tablic), więc każde żądanie robi
``copy.copy(base)`` i woła ``update_observer`` na kopii — bez globalnego locka.

Niebo: ``get_topocentric_vectors`` + wzory pętli głównej ``geografia.py:2802-2834`` i statusy
HUD ``geografia.py:2951-2965``.
"""

import copy
import math
import threading
from collections import OrderedDict

import numpy as np
from fastapi import APIRouter, HTTPException, Response

from app.core.contracts import CONTRACT_VERSION, ReferenceFrame, ResponseMeta, SelenoPoint
from app.core.facade import BaseFacade
from app.core.legacy import import_root_script
from app.features.lunar_surface.contract import (
    EarthInSky,
    HorizonProfile,
    LunarSky,
    ObserverGeometry,
    ObserverGeometryQuery,
    StarField,
    SunInSky,
    SurfaceCatalog,
    SurfaceQuery,
    TileSetInfo,
)
from app.features.lunar_surface.year_data import load_year, time_index

DEM_FILE = "moon_dem_nasa_16ppd_v3.npy"
COLOR_FILE = "moon_color_nasa_8k_v3.npy"
DEM_SOURCE = "NASA LOLA 16 px/deg"  # ten sam opis co geografia.py:365
DEM_TILE = 180      # 2880×5760 → 16×32 kafli (11.25°)
ALBEDO_TILE = 256   # 4096×8192 → 16×32 kafli
OBSERVER_CACHE_SIZE = 64
TILE_CACHE_CONTROL = "public, max-age=86400"
TILE_URL = "/api/v1/lunar_surface/tiles/{layer}/{{ty}}/{{tx}}"


def _vec(v) -> tuple:
    return (float(v[0]), float(v[1]), float(v[2]))


class LunarSurfaceFacade(BaseFacade):
    feature_id = "lunar_surface"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.geo = import_root_script("geografia", ctx.settings.scripts_dir)
        self._terrain_obj = None
        self._terrain_lock = threading.Lock()   # tylko budowa bazowego terenu
        # (lat, lon, eye) → kopia terenu po update_observer (LRU); sky dla znanego obserwatora
        # nie przelicza horyzontu.
        self._observers: "OrderedDict[tuple, object]" = OrderedDict()
        self._observers_lock = threading.Lock()

    # --- pomocnicze ----------------------------------------------------------------------

    def _meta(self, endpoint: str) -> ResponseMeta:
        return ResponseMeta(
            feature=self.feature_id, endpoint=endpoint, contract_version=CONTRACT_VERSION,
            source="computed", frame=ReferenceFrame.TOPOCENTRIC_HORIZON,
            units={"angle": "deg", "distance": "km", "elevation": "m"},
        )

    def _terrain(self):
        """Leniwie tworzy bazowy ``LunarTerrain3D`` (bez ``gl``); równoległe pierwsze wywołania czekają."""
        if self._terrain_obj is not None:
            return self._terrain_obj
        with self._terrain_lock:
            if self._terrain_obj is None:
                tex = self.ctx.settings.textures_dir
                dem_path, color_path = tex / DEM_FILE, tex / COLOR_FILE
                if not (dem_path.is_file() and color_path.is_file()):
                    raise HTTPException(503, f"Terrain maps v3 ({DEM_FILE}, {COLOR_FILE}) not found in {tex}")
                dem = np.load(dem_path, mmap_mode="r")
                color = np.load(color_path, mmap_mode="r")
                if dem.ndim != 2 or dem.shape[0] % DEM_TILE or dem.shape[1] % DEM_TILE:
                    raise HTTPException(503, f"DEM {dem.shape} does not split into {DEM_TILE} px tiles")
                if color.ndim != 3 or color.shape[2] != 3 or color.shape[0] % ALBEDO_TILE or color.shape[1] % ALBEDO_TILE:
                    raise HTTPException(503, f"Albedo {color.shape} does not split into {ALBEDO_TILE} px tiles")
                self._terrain_obj = self.geo.LunarTerrain3D(dem, color)
        return self._terrain_obj

    def _observe(self, lat_deg: float, lon_deg: float, eye_height_m: float):
        """Kopia bazowego terenu z ``update_observer`` dla obserwatora (LRU 64)."""
        key = (lat_deg, lon_deg, eye_height_m)
        with self._observers_lock:
            t = self._observers.get(key)
            if t is not None:
                self._observers.move_to_end(key)
                return t
        t = copy.copy(self._terrain())
        t.update_observer(lat_deg, lon_deg, eye_height_m=eye_height_m)
        with self._observers_lock:
            self._observers[key] = t
            self._observers.move_to_end(key)
            while len(self._observers) > OBSERVER_CACHE_SIZE:
                self._observers.popitem(last=False)
        return t

    # --- endpointy -----------------------------------------------------------------------

    def catalog(self) -> SurfaceCatalog:
        base = self._terrain()
        cls = self.geo.LunarTerrain3D

        def tiles(layer, w, h, tw, th, dtype, ch):
            return TileSetInfo(width=w, height=h, tile_w=tw, tile_h=th, nx=w // tw, ny=h // th,
                               dtype=dtype, channels=ch, url_template=TILE_URL.format(layer=layer))

        return SurfaceCatalog(
            meta=self._meta("catalog"),
            r_moon_km=self.geo.R_MOON,
            dem_source=DEM_SOURCE,
            dem=tiles("dem", base.W, base.H, DEM_TILE, DEM_TILE, "float32", 1),
            albedo=tiles("albedo", base.AW, base.AH, ALBEDO_TILE, ALBEDO_TILE,
                         "uint8" if base.albedo_is_u8 else "float32", 3),
            albedo_is_u8=bool(base.albedo_is_u8),
            albedo_scale=1.0 if base.albedo_is_u8 else 0.40,   # geografia.py:1648-1654
            patch_n=cls.PATCH_N, tau_px=cls.TAU_PX, max_patches=cls.MAX_PATCHES,
            min_cell_scale=cls.MIN_CELL_SCALE,
        )

    def observer(self, q: ObserverGeometryQuery) -> ObserverGeometry:
        t = self._observe(q.lat_deg, q.lon_deg, q.eye_height_m)
        n = len(t.az_grid)
        return ObserverGeometry(
            meta=self._meta("observer"),
            observer=SelenoPoint(lat_deg=q.lat_deg, lon_deg=q.lon_deg),
            eye_height_m=q.eye_height_m,
            observer_elevation_km=float(t.obs_elev_km),
            observer_radius_km=float(t.obs_radius_km),
            r_max_km=float(t.r_max_km),
            slope_deg=float(t.obs_slope_deg),
            slope_dir=t.obs_slope_dir,
            horizon=HorizonProfile(
                az_deg=np.degrees(t.az_grid[:n]).tolist(),
                alt_deg=np.degrees(t.horizon_alt[:n]).tolist(),
                distance_km=np.asarray(t.horizon_dist_km[:n], dtype=float).tolist(),
                lat_deg=np.asarray(t.horizon_lat[:n], dtype=float).tolist(),
                lon_deg=np.asarray(t.horizon_lon[:n], dtype=float).tolist(),
                elevation_km=np.asarray(t.horizon_elev_km[:n], dtype=float).tolist(),
            ),
        )

    def tile_bytes(self, layer: str, ty: int, tx: int) -> bytes:
        """Surowe bajty kafla: ``dem`` float32 LE (180×180), ``albedo`` uint8 RGB (256×256×3)."""
        base = self._terrain()
        if layer == "dem":
            arr, tile, dtype = base.dem, DEM_TILE, "<f4"
        elif layer == "albedo":
            arr, tile, dtype = base.albedo_map, ALBEDO_TILE, None
        else:
            raise HTTPException(404, f"Unknown tile layer: {layer}")
        ny, nx = arr.shape[0] // tile, arr.shape[1] // tile
        if not (0 <= ty < ny and 0 <= tx < nx):
            raise HTTPException(404, f"Tile {ty}/{tx} is outside the {ny}×{nx} grid")
        block = arr[ty * tile:(ty + 1) * tile, tx * tile:(tx + 1) * tile]
        if dtype is None:   # albedo: uint8 RGB (albedo_is_u8); inaczej skala jak w _init_gpu
            if base.albedo_is_u8:
                block = np.ascontiguousarray(block, dtype=np.uint8)
            else:
                block = np.ascontiguousarray(np.clip(block / 0.40 * 255.0, 0.0, 255.0), dtype=np.uint8)
        else:
            block = np.ascontiguousarray(block, dtype=dtype)
        return block.tobytes()

    # --- endpointy -----------------------------------------------------------------------

    def sky(self, q: SurfaceQuery) -> LunarSky:
        nl = self.geo
        year, idx = time_index(q.t)
        year_data = load_year(self.ctx.settings.coords_dir, year, nl.J2000)
        idx = min(idx, len(year_data["times"]) - 1)

        t = self._observe(q.lat_deg, q.lon_deg, q.eye_height_m)
        data = nl.get_topocentric_vectors(year_data, idx, q.lat_deg, q.lon_deg, obs_radius_km=t.obs_radius_km)
        earth_alt, earth_az, earth_dist = data["earth"]
        sun_alt, sun_az, sun_dist = data["sun"]

        earth_hor = t.get_horizon_at_azimuth(earth_az)
        sun_hor = t.get_horizon_at_azimuth(sun_az)
        obs_elev_km = t.obs_elev_km
        obs_radius_km = t.obs_radius_km

        # --- geografia.py:2802-2834 ---
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

        # --- statusy HUD, geografia.py:2951-2965 ---
        earth_visible = earth_alt + ang_earth > earth_hor
        earth_vis = "VISIBLE" if earth_visible else "BELOW HORIZON"
        if sun_horizon_vis <= 0.0:
            sun_vis = "BELOW HORIZON"
        elif sun_eclipse_occ >= 0.995:
            sun_vis = "ECLIPSED BY EARTH 100%"
        elif sun_eclipse_occ > 0.01:
            sun_vis = f"ECLIPSED {sun_eclipse_occ * 100:.0f}%"
        elif sun_horizon_vis < 0.995:
            sun_vis = f"ON HORIZON ({sun_horizon_vis * 100:.0f}%)"
        else:
            sun_vis = "VISIBLE"

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
            sun_distance_from_earth_km=float(data["sun_dist_from_earth"]),
            earth_axes_enu=tuple(_vec(a) for a in data["ecef_axes_enu"]),
            ecliptic_to_enu=tuple(_vec(row) for row in ecl_to_enu),
        )

    def stars(self) -> StarField:
        """Gwiazdy dokładnie jak w ``geografia.main()`` (``geografia.py:2602-2612``).

        ``np.random.seed(42)`` + kolejne wywołania globalnego generatora to ta sama sekwencja co
        ``RandomState(42)`` — bez ruszania globalnego stanu numpy w procesie serwera.
        """
        rng = np.random.RandomState(42)
        n_stars = 1200
        star_lam = rng.uniform(0, 2 * np.pi, n_stars)
        star_beta = np.arcsin(rng.uniform(-1, 1, n_stars))
        star_mags = rng.randint(90, 255, n_stars)
        stars_ecl = np.stack([
            np.cos(star_beta) * np.cos(star_lam),
            np.cos(star_beta) * np.sin(star_lam),
            np.sin(star_beta),
        ], axis=-1)
        meta = self._meta("stars")
        meta.frame = ReferenceFrame.ECLIPTIC_J2000_GEOCENTRIC
        return StarField(meta=meta, ecliptic_xyz=[_vec(v) for v in stars_ecl], brightness=star_mags.tolist())


def tile_routes(facade: LunarSurfaceFacade) -> APIRouter:
    """Trasa binarna kafli: ``GET /api/v1/lunar_surface/tiles/{layer}/{ty}/{tx}``."""
    router = APIRouter()

    @router.get("/tiles/{layer}/{ty}/{tx}", summary="Kafel DEM (float32) lub albedo (uint8 RGB)")
    def tile(layer: str, ty: int, tx: int) -> Response:
        return Response(content=facade.tile_bytes(layer, ty, tx), media_type="application/octet-stream",
                        headers={"Cache-Control": TILE_CACHE_CONTROL})

    return router
