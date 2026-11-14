import os
import sys
import csv
import math
import ctypes
import ctypes.util
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


class GL33:
    """Lekki interfejs OpenGL 3.3 Core przez ctypes (zoptymalizowany pod Intel UHD Graphics 620)."""

    DEPTH_BUFFER_BIT = 0x00000100
    COLOR_BUFFER_BIT = 0x00004000
    POINTS = 0x0000
    LINES = 0x0001
    LINE_STRIP = 0x0003
    TRIANGLES = 0x0004
    TRIANGLE_STRIP = 0x0005
    SRC_ALPHA = 0x0302
    ONE_MINUS_SRC_ALPHA = 0x0303
    CCW = 0x0901
    CULL_FACE = 0x0B44
    DEPTH_TEST = 0x0B71
    BLEND = 0x0BE2
    UNPACK_ALIGNMENT = 0x0CF5
    TEXTURE_2D = 0x0DE1
    UNSIGNED_BYTE = 0x1401
    UNSIGNED_INT = 0x1405
    FLOAT = 0x1406
    RED = 0x1903
    RGB = 0x1907
    RGBA = 0x1908
    NEAREST = 0x2600
    LINEAR = 0x2601
    LINEAR_MIPMAP_LINEAR = 0x2703
    TEXTURE_MAG_FILTER = 0x2800
    TEXTURE_MIN_FILTER = 0x2801
    TEXTURE_WRAP_S = 0x2802
    TEXTURE_WRAP_T = 0x2803
    REPEAT = 0x2901
    POLYGON_OFFSET_FILL = 0x8037
    RGB8 = 0x8051
    RGBA8 = 0x8058
    CLAMP_TO_EDGE = 0x812F
    TEXTURE_MAX_LEVEL = 0x813D
    R8 = 0x8229
    R32F = 0x822E
    TEXTURE0 = 0x84C0
    ARRAY_BUFFER = 0x8892
    ELEMENT_ARRAY_BUFFER = 0x8893
    STATIC_DRAW = 0x88E4
    DYNAMIC_DRAW = 0x88E8
    FRAGMENT_SHADER = 0x8B30
    VERTEX_SHADER = 0x8B31
    COMPILE_STATUS = 0x8B81
    LINK_STATUS = 0x8B82

    def __init__(self):
        gl_path = ctypes.util.find_library("GL") or "libGL.so.1"
        self._lib = ctypes.CDLL(gl_path)

        self._get_proc = None
        if hasattr(self._lib, "glXGetProcAddressARB"):
            fn = self._lib.glXGetProcAddressARB
            fn.argtypes = [ctypes.c_char_p]
            fn.restype = ctypes.c_void_p
            self._get_proc = fn
        else:
            egl_path = ctypes.util.find_library("EGL") or "libEGL.so.1"
            try:
                egl_lib = ctypes.CDLL(egl_path)
                fn = egl_lib.eglGetProcAddress
                fn.argtypes = [ctypes.c_char_p]
                fn.restype = ctypes.c_void_p
                self._get_proc = fn
            except Exception:
                pass

        c_int = ctypes.c_int
        c_uint = ctypes.c_uint
        c_float = ctypes.c_float
        c_void_p = ctypes.c_void_p
        c_char_p = ctypes.c_char_p
        c_ssize_t = ctypes.c_ssize_t
        p_uint = ctypes.POINTER(c_uint)
        p_int = ctypes.POINTER(c_int)
        p_float = ctypes.POINTER(c_float)

        self.glViewport = self._bind("glViewport", None, [c_int, c_int, c_int, c_int])
        self.glClearColor = self._bind("glClearColor", None, [c_float, c_float, c_float, c_float])
        self.glClear = self._bind("glClear", None, [c_uint])
        self.glEnable = self._bind("glEnable", None, [c_uint])
        self.glDisable = self._bind("glDisable", None, [c_uint])
        self.glBlendFunc = self._bind("glBlendFunc", None, [c_uint, c_uint])
        self.glFrontFace = self._bind("glFrontFace", None, [c_uint])
        self.glPolygonOffset = self._bind("glPolygonOffset", None, [c_float, c_float])
        self.glLineWidth = self._bind("glLineWidth", None, [c_float])
        self.glPixelStorei = self._bind("glPixelStorei", None, [c_uint, c_int])

        self.glCreateShader = self._bind("glCreateShader", c_uint, [c_uint])
        self.glShaderSource = self._bind("glShaderSource", None, [c_uint, c_int, ctypes.POINTER(c_char_p), p_int])
        self.glCompileShader = self._bind("glCompileShader", None, [c_uint])
        self.glGetShaderiv = self._bind("glGetShaderiv", None, [c_uint, c_uint, p_int])
        self.glGetShaderInfoLog = self._bind("glGetShaderInfoLog", None, [c_uint, c_int, p_int, c_char_p])
        self.glDeleteShader = self._bind("glDeleteShader", None, [c_uint])

        self.glCreateProgram = self._bind("glCreateProgram", c_uint, [])
        self.glAttachShader = self._bind("glAttachShader", None, [c_uint, c_uint])
        self.glLinkProgram = self._bind("glLinkProgram", None, [c_uint])
        self.glGetProgramiv = self._bind("glGetProgramiv", None, [c_uint, c_uint, p_int])
        self.glGetProgramInfoLog = self._bind("glGetProgramInfoLog", None, [c_uint, c_int, p_int, c_char_p])
        self.glUseProgram = self._bind("glUseProgram", None, [c_uint])

        self.glGetUniformLocation = self._bind("glGetUniformLocation", c_int, [c_uint, c_char_p])
        self.glUniform1i = self._bind("glUniform1i", None, [c_int, c_int])
        self.glUniform1f = self._bind("glUniform1f", None, [c_int, c_float])
        self.glUniform2f = self._bind("glUniform2f", None, [c_int, c_float, c_float])
        self.glUniform3f = self._bind("glUniform3f", None, [c_int, c_float, c_float, c_float])
        self.glUniform4f = self._bind("glUniform4f", None, [c_int, c_float, c_float, c_float, c_float])
        self.glUniformMatrix3fv = self._bind("glUniformMatrix3fv", None, [c_int, c_int, ctypes.c_ubyte, p_float])

        self.glGetAttribLocation = self._bind("glGetAttribLocation", c_int, [c_uint, c_char_p])
        self.glEnableVertexAttribArray = self._bind("glEnableVertexAttribArray", None, [c_uint])
        self.glVertexAttribPointer = self._bind(
            "glVertexAttribPointer", None, [c_uint, c_int, c_uint, ctypes.c_ubyte, c_int, c_void_p]
        )
        self.glVertexAttribDivisor = self._bind("glVertexAttribDivisor", None, [c_uint, c_uint])

        self.glGenVertexArrays = self._bind("glGenVertexArrays", None, [c_int, p_uint])
        self.glBindVertexArray = self._bind("glBindVertexArray", None, [c_uint])

        self.glGenBuffers = self._bind("glGenBuffers", None, [c_int, p_uint])
        self.glBindBuffer = self._bind("glBindBuffer", None, [c_uint, c_uint])
        self.glBufferData = self._bind("glBufferData", None, [c_uint, c_ssize_t, c_void_p, c_uint])
        self.glBufferSubData = self._bind("glBufferSubData", None, [c_uint, c_ssize_t, c_ssize_t, c_void_p])

        self.glGenTextures = self._bind("glGenTextures", None, [c_int, p_uint])
        self.glDeleteTextures = self._bind("glDeleteTextures", None, [c_int, p_uint])
        self.glActiveTexture = self._bind("glActiveTexture", None, [c_uint])
        self.glBindTexture = self._bind("glBindTexture", None, [c_uint, c_uint])
        self.glTexParameteri = self._bind("glTexParameteri", None, [c_uint, c_uint, c_int])
        self.glTexImage2D = self._bind(
            "glTexImage2D", None, [c_uint, c_int, c_int, c_int, c_int, c_int, c_uint, c_uint, c_void_p]
        )
        self.glTexSubImage2D = self._bind(
            "glTexSubImage2D", None, [c_uint, c_int, c_int, c_int, c_int, c_int, c_uint, c_uint, c_void_p]
        )
        self.glGenerateMipmap = self._bind("glGenerateMipmap", None, [c_uint])

        self.glDrawArrays = self._bind("glDrawArrays", None, [c_uint, c_int, c_int])
        self.glDrawElements = self._bind("glDrawElements", None, [c_uint, c_int, c_uint, c_void_p])
        self.glDrawElementsInstanced = self._bind(
            "glDrawElementsInstanced", None, [c_uint, c_int, c_uint, c_void_p, c_int]
        )

        self.glPixelStorei(self.UNPACK_ALIGNMENT, 1)

    def _bind(self, name, restype, argtypes):
        proto = ctypes.CFUNCTYPE(restype, *argtypes)
        addr = self._get_proc(name.encode("ascii")) if self._get_proc else None
        if addr:
            return proto(addr)
        return proto((name, self._lib))

    def create_program(self, vs_src: str, fs_src: str) -> int:
        def _compile(shader_type, src):
            sh = self.glCreateShader(shader_type)
            src_bytes = src.encode("utf-8")
            c_src = ctypes.c_char_p(src_bytes)
            self.glShaderSource(sh, 1, ctypes.byref(c_src), None)
            self.glCompileShader(sh)
            status = ctypes.c_int(0)
            self.glGetShaderiv(sh, self.COMPILE_STATUS, ctypes.byref(status))
            if not status.value:
                log = ctypes.create_string_buffer(2048)
                self.glGetShaderInfoLog(sh, 2048, None, log)
                raise RuntimeError(f"Błąd kompilacji shadera:\n{log.value.decode('utf-8', errors='replace')}")
            return sh

        vs = _compile(self.VERTEX_SHADER, vs_src)
        fs = _compile(self.FRAGMENT_SHADER, fs_src)
        prog = self.glCreateProgram()
        self.glAttachShader(prog, vs)
        self.glAttachShader(prog, fs)
        self.glLinkProgram(prog)
        status = ctypes.c_int(0)
        self.glGetProgramiv(prog, self.LINK_STATUS, ctypes.byref(status))
        if not status.value:
            log = ctypes.create_string_buffer(2048)
            self.glGetProgramInfoLog(prog, 2048, None, log)
            raise RuntimeError(f"Błąd linkowania programu GLSL:\n{log.value.decode('utf-8', errors='replace')}")
        self.glDeleteShader(vs)
        self.glDeleteShader(fs)
        return prog

    def gen_vao(self) -> int:
        v = ctypes.c_uint(0)
        self.glGenVertexArrays(1, ctypes.byref(v))
        return v.value

    def gen_buffer(self) -> int:
        b = ctypes.c_uint(0)
        self.glGenBuffers(1, ctypes.byref(b))
        return b.value

    def gen_texture(self) -> int:
        t = ctypes.c_uint(0)
        self.glGenTextures(1, ctypes.byref(t))
        return t.value

    def delete_texture(self, tex_id: int):
        t = ctypes.c_uint(tex_id)
        self.glDeleteTextures(1, ctypes.byref(t))


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

    dem_v3 = os.path.join("Textures", "moon_dem_nasa_16ppd_v3.npy")
    color_v3 = os.path.join("Textures", "moon_color_nasa_8k_v3.npy")
    if os.path.exists(dem_v3) and os.path.exists(color_v3):
        try:
            dem = np.load(dem_v3, mmap_mode="r")
            color_u8 = np.load(color_v3, mmap_mode="r")
            if dem.ndim == 2 and color_u8.ndim == 3 and color_u8.shape[2] == 3:
                return dem, color_u8, "NASA LOLA 16 px/deg"
        except Exception as e:
            print(f"[OSTRZEŻENIE] Nie udało się wczytać map v3: {e}")

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
            surf = pygame.image.load(path).convert(24)
            print(f"[OK] Wczytano teksturę {label}: {path} ({surf.get_width()}x{surf.get_height()})")
            return np.ascontiguousarray(pygame.surfarray.array3d(surf).transpose(1, 0, 2))
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


class GPURenderer:
    """Potok renderowania OpenGL 3.3 dla nieba, Słońca, Ziemi i nakładki HUD."""

    _STAR_VS = """
    #version 330 core
    in vec3 in_ecl;
    in float in_mag;

    uniform mat3 u_R_body;
    uniform vec3 u_north;
    uniform vec3 u_east;
    uniform vec3 u_up;
    uniform vec3 u_fwd;
    uniform vec3 u_right;
    uniform vec3 u_cam_up;
    uniform float u_cw;
    uniform float u_ch;
    uniform float u_focal;

    out float v_mag;

    void main() {
        vec3 sb = u_R_body * in_ecl;
        float sn = dot(sb, u_north);
        float se = dot(sb, u_east);
        float su = dot(sb, u_up);

        float s_alt = asin(clamp(su, -1.0, 1.0));
        if (s_alt <= -0.1) {
            gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
            gl_PointSize = 1.0;
            v_mag = 0.0;
            return;
        }
        float s_az = atan(se, sn);
        float ca = cos(s_alt);
        vec3 p = vec3(ca * cos(s_az), ca * sin(s_az), sin(s_alt));

        float z_cam = dot(p, u_fwd);
        if (z_cam <= 0.05) {
            gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
            gl_PointSize = 1.0;
            v_mag = 0.0;
            return;
        }
        float x_cam = dot(p, u_right);
        float y_cam = dot(p, u_cam_up);
        float sx = u_cw * 0.5 + (x_cam / z_cam) * u_focal;
        float sy = u_ch * 0.5 - (y_cam / z_cam) * u_focal;

        gl_Position = vec4((sx / u_cw) * 2.0 - 1.0, 1.0 - (sy / u_ch) * 2.0, 0.0, 1.0);
        gl_PointSize = 1.0;
        v_mag = in_mag;
    }
    """

    _STAR_FS = """
    #version 330 core
    in float v_mag;
    out vec4 out_color;
    void main() {
        out_color = vec4(v_mag, v_mag, v_mag, 1.0);
    }
    """

    _GRID_VS = """
    #version 330 core
    in vec3 in_enu;

    uniform vec3 u_fwd;
    uniform vec3 u_right;
    uniform vec3 u_cam_up;
    uniform float u_tan_x;
    uniform float u_tan_y;

    void main() {
        float zc = dot(in_enu, u_fwd);
        float xc = dot(in_enu, u_right);
        float yc = dot(in_enu, u_cam_up);
        gl_Position = vec4(xc / u_tan_x, yc / u_tan_y, 0.0, zc);
    }
    """

    _GRID_FS = """
    #version 330 core
    uniform vec4 u_color;
    out vec4 out_color;
    void main() {
        out_color = u_color;
    }
    """

    _QUAD_VS = """
    #version 330 core
    in vec2 in_pos;
    in vec2 in_uv;
    out vec2 v_uv;
    void main() {
        gl_Position = vec4(in_pos, 0.0, 1.0);
        v_uv = in_uv;
    }
    """

    _SUN_FS = """
    #version 330 core
    uniform float u_sx;
    uniform float u_sy;
    uniform float u_r_sun;
    uniform float u_halo_mult;
    uniform float u_ch;

    out vec4 out_color;

    void main() {
        float px = gl_FragCoord.x - 0.5;
        float py = u_ch - gl_FragCoord.y - 0.5;
        float gx = (px - u_sx) / u_r_sun;
        float gy = (py - u_sy) / u_r_sun;
        float dist = sqrt(gx * gx + gy * gy);

        if (dist <= 1.0) {
            float mu = sqrt(clamp(1.0 - dist * dist, 0.0, 1.0));
            float limb_dark = 0.45 + 0.55 * pow(mu, 0.50);
            if (u_r_sun > 18.0) {
                float granulation = 0.028 * sin(gx * 55.0) * cos(gy * 55.0);
                limb_dark = clamp(limb_dark + granulation, 0.25, 1.05);
            }
            float r = clamp(min(1.0, limb_dark * 1.06), 0.0, 1.0);
            float g = clamp((246.0 / 255.0) * limb_dark, 0.0, 1.0);
            float b = clamp((218.0 / 255.0) * pow(limb_dark, 1.15), 0.0, 1.0);
            out_color = vec4(r, g, b, 1.0);
        } else if (dist <= u_halo_mult) {
            float t_c = (dist - 1.0) / (u_halo_mult - 1.0);
            float glow = exp(-2.6 * t_c) * (1.0 - t_c);
            float alpha = clamp((220.0 / 255.0) * glow, 0.0, 1.0);
            out_color = vec4(1.0, 228.0 / 255.0, 165.0 / 255.0, alpha);
        } else {
            discard;
        }
    }
    """

    _EARTH_FS = """
    #version 330 core
    const float PI = 3.14159265358979323846;
    const float R_EARTH = 6371.0;
    const float R_MOON = 1737.4;
    const float R_SUN = 696340.0;

    uniform float u_ex;
    uniform float u_ey;
    uniform float u_r_earth;
    uniform float u_ch;

    uniform vec3 u_e_x_cam;
    uniform vec3 u_e_y_cam;
    uniform vec3 u_e_z_cam;

    uniform vec3 u_x_ecef;
    uniform vec3 u_y_ecef;
    uniform vec3 u_z_ecef;

    uniform vec3 u_sun_from_earth_enu;
    uniform vec3 u_moon_from_earth_enu;
    uniform float u_moon_sun_dot;
    uniform float u_sun_dist_km;
    uniform float u_cloud_offset;
    uniform float u_eclipse_ring_factor;
    uniform float u_dark_side_exposure;

    uniform int u_has_day;
    uniform int u_has_night;
    uniform int u_has_clouds;
    uniform float u_night_lod;

    uniform sampler2D u_tex_day;
    uniform sampler2D u_tex_night;
    uniform sampler2D u_tex_clouds;

    out vec4 out_color;

    void main() {
        float px = gl_FragCoord.x - 0.5;
        float py = u_ch - gl_FragCoord.y - 0.5;
        float gx = (px - u_ex) / u_r_earth;
        float gy = (py - u_ey) / u_r_earth;
        float dist_sq = gx * gx + gy * gy;

        if (dist_sq <= 1.0) {
            float gz = sqrt(1.0 - dist_sq);
            vec3 n_enu = gx * u_e_x_cam - gy * u_e_y_cam + gz * u_e_z_cam;

            float px_e = dot(n_enu, u_x_ecef);
            float py_e = dot(n_enu, u_y_ecef);
            float pz_e = dot(n_enu, u_z_ecef);

            float lat_pt = asin(clamp(pz_e, -1.0, 1.0));
            float lon_pt = atan(py_e, px_e);

            float u = (lon_pt + PI) / (2.0 * PI);
            float v = (PI * 0.5 - lat_pt) / PI;

            vec3 day_rgb;
            if (u_has_day == 1) {
                day_rgb = texture(u_tex_day, vec2(u, v)).rgb;
            } else {
                float continent = sin(lon_pt * 2.1 + 0.4) * cos(lat_pt * 2.3)
                                + 0.55 * cos(lon_pt * 4.7 - 1.1) * sin(lat_pt * 3.8 + 0.3)
                                + 0.30 * sin(lon_pt * 9.0 + lat_pt * 7.0);
                bool is_land = continent > 0.18;
                bool is_ice = abs(lat_pt) > radians(72.0 - 8.0 * continent);
                day_rgb = vec3(22.0 / 255.0, 72.0 / 255.0, 158.0 / 255.0);
                if (is_land) day_rgb = vec3(64.0 / 255.0, 118.0 / 255.0, 62.0 / 255.0);
                if (is_ice) day_rgb = vec3(235.0 / 255.0, 242.0 / 255.0, 248.0 / 255.0);
            }

            vec3 night_rgb;
            if (u_has_night == 1) {
                vec3 raw_night = textureLod(u_tex_night, vec2(u, v), u_night_lod).rgb;
                vec3 clean_night = clamp((raw_night - 0.055) / 0.945, 0.0, 1.0);
                night_rgb = pow(clean_night, vec3(0.88)) * (1.15 * u_dark_side_exposure);
            } else {
                float continent = sin(lon_pt * 2.1 + 0.4) * cos(lat_pt * 2.3)
                                + 0.55 * cos(lon_pt * 4.7 - 1.1) * sin(lat_pt * 3.8 + 0.3);
                bool urban = (continent > 0.22)
                          && (abs(lat_pt) < radians(60.0))
                          && (sin(lon_pt * 28.0) * cos(lat_pt * 34.0) > 0.65);
                night_rgb = urban ? vec3(235.0 / 255.0, 175.0 / 255.0, 80.0 / 255.0) * u_dark_side_exposure
                                  : vec3(0.0);
            }

            float cos_sun = dot(n_enu, u_sun_from_earth_enu);
            float twilight_t = clamp((cos_sun + 0.07) / 0.15, 0.0, 1.0);
            float day_blend = twilight_t * twilight_t * (3.0 - 2.0 * twilight_t);
            float sun_diffuse = pow(clamp(cos_sun, 0.0, 1.0), 0.78);

            if (u_moon_sun_dot > 0.0) {
                vec3 pts_earth_km = R_EARTH * n_enu;
                vec3 rel_to_moon = pts_earth_km - u_moon_from_earth_enu;
                float along_sun = dot(rel_to_moon, u_sun_from_earth_enu);
                if (along_sun < 0.0) {
                    float dist_behind = -along_sun;
                    vec3 perp_vec = rel_to_moon + dist_behind * u_sun_from_earth_enu;
                    float perp_dist = length(perp_vec);

                    float r_penumbra = R_MOON + dist_behind * (R_SUN + R_MOON) / max(1.0, u_sun_dist_km);
                    float r_umbra = max(0.0, R_MOON - dist_behind * (R_SUN - R_MOON) / max(1.0, u_sun_dist_km));

                    if (perp_dist < r_penumbra) {
                        float pen_t = clamp(
                            (perp_dist - r_umbra) / max(r_penumbra - r_umbra, 1.0),
                            0.0,
                            1.0
                        );
                        float shadow_atten = 0.08 + 0.92 * (pen_t * pen_t * (3.0 - 2.0 * pen_t));
                        sun_diffuse *= shadow_atten;
                    }
                }
            }

            float terminator_glow = (cos_sun > -0.08) ? exp(-pow((cos_sun - 0.01) / 0.095, 2.0)) : 0.0;

            vec3 lit_day_rgb = day_rgb * (0.02 + 0.98 * sun_diffuse);
            lit_day_rgb.r += (36.0 / 255.0) * terminator_glow;
            lit_day_rgb.g += (12.0 / 255.0) * terminator_glow;

            if (u_has_clouds == 1) {
                float u_cloud = fract(u - u_cloud_offset);
                float c_raw = texture(u_tex_clouds, vec2(u_cloud, v)).r;
                float cloud_alpha = pow(clamp((c_raw - 0.04) / 0.96, 0.0, 1.0), 0.90) * 0.92;

                vec3 cloud_lit_rgb = vec3(
                    (252.0 / 255.0) * (0.03 + 0.97 * sun_diffuse) + (46.0 / 255.0) * terminator_glow,
                    (253.0 / 255.0) * (0.03 + 0.97 * sun_diffuse) + (16.0 / 255.0) * terminator_glow,
                    1.0 * (0.04 + 0.96 * sun_diffuse)
                );
                lit_day_rgb = mix(lit_day_rgb, cloud_lit_rgb, cloud_alpha);
                night_rgb *= (1.0 - 0.55 * cloud_alpha);
            }

            float twilight_cities = pow(clamp((0.04 - cos_sun) / 0.14, 0.0, 1.0), 1.4);
            vec3 out_rgb = lit_day_rgb * day_blend + night_rgb * twilight_cities;

            float limb_geom = pow(1.0 - gz, 2.6);
            float day_limb = limb_geom * clamp(cos_sun + 0.22, 0.0, 1.0) * (1.0 - 0.75 * u_eclipse_ring_factor);
            float ecl_limb = limb_geom * u_eclipse_ring_factor;

            out_rgb.r += (75.0 / 255.0) * day_limb + (245.0 / 255.0) * ecl_limb;
            out_rgb.g += (155.0 / 255.0) * day_limb + (95.0 / 255.0) * ecl_limb;
            out_rgb.b += (250.0 / 255.0) * day_limb + (35.0 / 255.0) * ecl_limb;

            out_color = vec4(clamp(out_rgb, 0.0, 1.0), 1.0);
        } else if (dist_sq <= 1.28) {
            float dist_h = sqrt(dist_sq);
            float h_fade = pow(clamp(1.0 - (dist_h - 1.0) / 0.13, 0.0, 1.0), 2.0);
            vec3 n_halo = gx * u_e_x_cam - gy * u_e_y_cam;
            float sun_facing = clamp(dot(n_halo, u_sun_from_earth_enu) + 0.30, 0.04, 1.0);
            float halo_strength = max(sun_facing, 0.85 * u_eclipse_ring_factor);

            vec3 halo_col = mix(
                vec3(75.0 / 255.0, 155.0 / 255.0, 250.0 / 255.0),
                vec3(235.0 / 255.0, 88.0 / 255.0, 32.0 / 255.0),
                u_eclipse_ring_factor
            );
            float alpha = clamp((150.0 / 255.0) * h_fade * halo_strength, 0.0, 1.0);
            out_color = vec4(halo_col, alpha);
        } else {
            discard;
        }
    }
    """

    _HUD_FS = """
    #version 330 core
    in vec2 v_uv;
    uniform sampler2D u_tex_hud;
    out vec4 out_color;
    void main() {
        out_color = texture(u_tex_hud, v_uv);
    }
    """

    def __init__(self, gl: GL33, stars_ecl: np.ndarray, star_mags: np.ndarray,
                 day_arr=None, night_mips=None, clouds_arr=None):
        self.gl = gl

        # 1. Program gwiazd
        self.prog_stars = gl.create_program(self._STAR_VS, self._STAR_FS)
        star_data = np.ascontiguousarray(
            np.column_stack([stars_ecl.astype(np.float32), (star_mags.astype(np.float32) / 255.0)]),
            dtype=np.float32,
        )
        self.n_stars = len(star_data)
        self.vao_stars = gl.gen_vao()
        self.vbo_stars = gl.gen_buffer()
        gl.glBindVertexArray(self.vao_stars)
        gl.glBindBuffer(gl.ARRAY_BUFFER, self.vbo_stars)
        gl.glBufferData(gl.ARRAY_BUFFER, star_data.nbytes, star_data.ctypes.data_as(ctypes.c_void_p), gl.STATIC_DRAW)
        loc_ecl = gl.glGetAttribLocation(self.prog_stars, b"in_ecl")
        loc_mag = gl.glGetAttribLocation(self.prog_stars, b"in_mag")
        gl.glEnableVertexAttribArray(loc_ecl)
        gl.glVertexAttribPointer(loc_ecl, 3, gl.FLOAT, 0, 16, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(loc_mag)
        gl.glVertexAttribPointer(loc_mag, 1, gl.FLOAT, 0, 16, ctypes.c_void_p(12))

        self.u_stars = {
            name: gl.glGetUniformLocation(self.prog_stars, name.encode("ascii"))
            for name in ("u_R_body", "u_north", "u_east", "u_up", "u_fwd", "u_right", "u_cam_up", "u_cw", "u_ch", "u_focal")
        }

        # 2. Program siatki azymutalnej
        self.prog_grid = gl.create_program(self._GRID_VS, self._GRID_FS)
        gl.glUseProgram(self.prog_grid)
        gl.glUniform4f(
            gl.glGetUniformLocation(self.prog_grid, b"u_color"),
            25.0 / 255.0, 35.0 / 255.0, 50.0 / 255.0, 1.0,
        )
        grid_segs = []
        for a_deg in range(0, 90, 30):
            a_rad = math.radians(a_deg)
            ca, sa = math.cos(a_rad), math.sin(a_rad)
            pts = [(ca * math.cos(math.radians(z)), ca * math.sin(math.radians(z)), sa) for z in range(0, 365, 5)]
            for i in range(len(pts) - 1):
                grid_segs.append(pts[i])
                grid_segs.append(pts[i + 1])
        grid_arr = np.ascontiguousarray(grid_segs, dtype=np.float32)
        self.n_grid_verts = len(grid_arr)
        self.vao_grid = gl.gen_vao()
        self.vbo_grid = gl.gen_buffer()
        gl.glBindVertexArray(self.vao_grid)
        gl.glBindBuffer(gl.ARRAY_BUFFER, self.vbo_grid)
        gl.glBufferData(gl.ARRAY_BUFFER, grid_arr.nbytes, grid_arr.ctypes.data_as(ctypes.c_void_p), gl.STATIC_DRAW)
        loc_enu = gl.glGetAttribLocation(self.prog_grid, b"in_enu")
        gl.glEnableVertexAttribArray(loc_enu)
        gl.glVertexAttribPointer(loc_enu, 3, gl.FLOAT, 0, 12, ctypes.c_void_p(0))

        self.u_grid = {
            name: gl.glGetUniformLocation(self.prog_grid, name.encode("ascii"))
            for name in ("u_fwd", "u_right", "u_cam_up", "u_tan_x", "u_tan_y")
        }

        # 3. Dynamiczny quad ekranowy (Słońce / Ziemia) i pełnoekranowy quad HUD
        self.prog_sun = gl.create_program(self._QUAD_VS, self._SUN_FS)
        self.prog_earth = gl.create_program(self._QUAD_VS, self._EARTH_FS)
        self.prog_hud = gl.create_program(self._QUAD_VS, self._HUD_FS)

        self.vbo_dyn_quad = gl.gen_buffer()
        gl.glBindBuffer(gl.ARRAY_BUFFER, self.vbo_dyn_quad)
        gl.glBufferData(gl.ARRAY_BUFFER, 4 * 4 * 4, None, gl.DYNAMIC_DRAW)

        def _make_quad_vao(prog, vbo):
            vao = gl.gen_vao()
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(gl.ARRAY_BUFFER, vbo)
            lp = gl.glGetAttribLocation(prog, b"in_pos")
            lu = gl.glGetAttribLocation(prog, b"in_uv")
            gl.glEnableVertexAttribArray(lp)
            gl.glVertexAttribPointer(lp, 2, gl.FLOAT, 0, 16, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(lu)
            gl.glVertexAttribPointer(lu, 2, gl.FLOAT, 0, 16, ctypes.c_void_p(8))
            return vao

        self.vao_sun = _make_quad_vao(self.prog_sun, self.vbo_dyn_quad)
        self.vao_earth = _make_quad_vao(self.prog_earth, self.vbo_dyn_quad)

        fs_quad = np.ascontiguousarray([
            -1.0,  1.0, 0.0, 0.0,
            -1.0, -1.0, 0.0, 1.0,
             1.0,  1.0, 1.0, 0.0,
             1.0, -1.0, 1.0, 1.0,
        ], dtype=np.float32)
        self.vbo_fs_quad = gl.gen_buffer()
        gl.glBindBuffer(gl.ARRAY_BUFFER, self.vbo_fs_quad)
        gl.glBufferData(gl.ARRAY_BUFFER, fs_quad.nbytes, fs_quad.ctypes.data_as(ctypes.c_void_p), gl.STATIC_DRAW)
        self.vao_hud = _make_quad_vao(self.prog_hud, self.vbo_fs_quad)

        self.u_sun = {
            name: gl.glGetUniformLocation(self.prog_sun, name.encode("ascii"))
            for name in ("u_sx", "u_sy", "u_r_sun", "u_halo_mult", "u_ch")
        }
        self.u_earth = {
            name: gl.glGetUniformLocation(self.prog_earth, name.encode("ascii"))
            for name in (
                "u_ex", "u_ey", "u_r_earth", "u_ch",
                "u_e_x_cam", "u_e_y_cam", "u_e_z_cam",
                "u_x_ecef", "u_y_ecef", "u_z_ecef",
                "u_sun_from_earth_enu", "u_moon_from_earth_enu",
                "u_moon_sun_dot", "u_sun_dist_km", "u_cloud_offset",
                "u_eclipse_ring_factor", "u_dark_side_exposure",
                "u_has_day", "u_has_night", "u_has_clouds", "u_night_lod",
                "u_tex_day", "u_tex_night", "u_tex_clouds",
            )
        }
        self.u_hud_tex = gl.glGetUniformLocation(self.prog_hud, b"u_tex_hud")

        # 4. Tekstury Ziemi w VRAM
        self.has_day = day_arr is not None
        self.tex_earth_day = gl.gen_texture()
        gl.glBindTexture(gl.TEXTURE_2D, self.tex_earth_day)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
        if self.has_day:
            dh, dw = day_arr.shape[:2]
            c_day = np.ascontiguousarray(day_arr, dtype=np.uint8)
            gl.glTexImage2D(gl.TEXTURE_2D, 0, gl.RGB8, dw, dh, 0, gl.RGB, gl.UNSIGNED_BYTE, c_day.ctypes.data_as(ctypes.c_void_p))
        else:
            dummy3 = (ctypes.c_ubyte * 3)(0, 0, 0)
            gl.glTexImage2D(gl.TEXTURE_2D, 0, gl.RGB8, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, dummy3)

        self.has_night = bool(night_mips)
        self.night_base_w = 1
        self.night_max_mip = 0
        self.tex_earth_night = gl.gen_texture()
        gl.glBindTexture(gl.TEXTURE_2D, self.tex_earth_night)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
        if self.has_night:
            self.night_base_w = night_mips[0].shape[1]
            self.night_max_mip = len(night_mips) - 1
            gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAX_LEVEL, self.night_max_mip)
            gl.glTexParameteri(
                gl.TEXTURE_2D,
                gl.TEXTURE_MIN_FILTER,
                gl.LINEAR_MIPMAP_LINEAR if self.night_max_mip > 0 else gl.LINEAR,
            )
            gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
            for lvl, mip in enumerate(night_mips):
                mh, mw = mip.shape[:2]
                c_mip = np.ascontiguousarray(mip, dtype=np.uint8)
                gl.glTexImage2D(gl.TEXTURE_2D, lvl, gl.RGB8, mw, mh, 0, gl.RGB, gl.UNSIGNED_BYTE, c_mip.ctypes.data_as(ctypes.c_void_p))
        else:
            gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
            gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
            dummy3 = (ctypes.c_ubyte * 3)(0, 0, 0)
            gl.glTexImage2D(gl.TEXTURE_2D, 0, gl.RGB8, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, dummy3)

        self.has_clouds = clouds_arr is not None
        self.tex_earth_clouds = gl.gen_texture()
        gl.glBindTexture(gl.TEXTURE_2D, self.tex_earth_clouds)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
        if self.has_clouds:
            ch_t, cw_t = clouds_arr.shape[:2]
            c_ch0 = np.ascontiguousarray(clouds_arr[:, :, 0], dtype=np.uint8)
            gl.glTexImage2D(gl.TEXTURE_2D, 0, gl.R8, cw_t, ch_t, 0, gl.RED, gl.UNSIGNED_BYTE, c_ch0.ctypes.data_as(ctypes.c_void_p))
        else:
            dummy1 = (ctypes.c_ubyte * 1)(0)
            gl.glTexImage2D(gl.TEXTURE_2D, 0, gl.R8, 1, 1, 0, gl.RED, gl.UNSIGNED_BYTE, dummy1)

        # 5. Tekstura nakładki HUD (z cache'owaniem)
        self.hud_size = (0, 0)
        self.hud_surface = None
        self.tex_hud = 0
        self._hud_dirty = True

    def get_hud_surface(self, cw: int, ch: int) -> pygame.Surface:
        gl = self.gl
        if self.hud_size != (cw, ch) or self.hud_surface is None:
            self.hud_size = (cw, ch)
            self.hud_surface = pygame.Surface((cw, ch), pygame.SRCALPHA)
            if self.tex_hud:
                gl.delete_texture(self.tex_hud)
            self.tex_hud = gl.gen_texture()
            gl.glBindTexture(gl.TEXTURE_2D, self.tex_hud)
            gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
            gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
            gl.glTexImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, cw, ch, 0, gl.RGBA, gl.UNSIGNED_BYTE, None)
            self._hud_dirty = True
        self.hud_surface.fill((0, 0, 0, 0))
        return self.hud_surface

    def upload_hud(self):
        if self.hud_surface is None or not self.tex_hud:
            return
        gl = self.gl
        cw, ch = self.hud_size
        raw = pygame.image.tobytes(self.hud_surface, "RGBA")
        gl.glActiveTexture(gl.TEXTURE0)
        gl.glBindTexture(gl.TEXTURE_2D, self.tex_hud)
        gl.glTexSubImage2D(gl.TEXTURE_2D, 0, 0, 0, cw, ch, gl.RGBA, gl.UNSIGNED_BYTE, raw)
        self._hud_dirty = False

    def _upload_screen_rect(self, x0: float, y0: float, x1: float, y1: float, cw: int, ch: int):
        nx0 = (x0 / cw) * 2.0 - 1.0
        nx1 = (x1 / cw) * 2.0 - 1.0
        ny0 = 1.0 - (y0 / ch) * 2.0
        ny1 = 1.0 - (y1 / ch) * 2.0
        verts = np.ascontiguousarray([
            nx0, ny0, 0.0, 0.0,
            nx0, ny1, 0.0, 1.0,
            nx1, ny0, 1.0, 0.0,
            nx1, ny1, 1.0, 1.0,
        ], dtype=np.float32)
        self.gl.glBindBuffer(self.gl.ARRAY_BUFFER, self.vbo_dyn_quad)
        self.gl.glBufferSubData(self.gl.ARRAY_BUFFER, 0, verts.nbytes, verts.ctypes.data_as(ctypes.c_void_p))

    def draw_stars(self, R_body, north, east, up, cam_basis, cw, ch, fov):
        gl = self.gl
        fwd, right, cam_up = cam_basis
        focal = (ch / 2.0) / math.tan(fov / 2.0)
        gl.glUseProgram(self.prog_stars)
        r_col = np.ascontiguousarray(R_body.T, dtype=np.float32)
        gl.glUniformMatrix3fv(self.u_stars["u_R_body"], 1, 0, r_col.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
        gl.glUniform3f(self.u_stars["u_north"], float(north[0]), float(north[1]), float(north[2]))
        gl.glUniform3f(self.u_stars["u_east"], float(east[0]), float(east[1]), float(east[2]))
        gl.glUniform3f(self.u_stars["u_up"], float(up[0]), float(up[1]), float(up[2]))
        gl.glUniform3f(self.u_stars["u_fwd"], float(fwd[0]), float(fwd[1]), float(fwd[2]))
        gl.glUniform3f(self.u_stars["u_right"], float(right[0]), float(right[1]), float(right[2]))
        gl.glUniform3f(self.u_stars["u_cam_up"], float(cam_up[0]), float(cam_up[1]), float(cam_up[2]))
        gl.glUniform1f(self.u_stars["u_cw"], float(cw))
        gl.glUniform1f(self.u_stars["u_ch"], float(ch))
        gl.glUniform1f(self.u_stars["u_focal"], float(focal))
        gl.glBindVertexArray(self.vao_stars)
        gl.glDrawArrays(gl.POINTS, 0, self.n_stars)

    def draw_grid(self, cam_basis, cw, ch, fov):
        gl = self.gl
        fwd, right, cam_up = cam_basis
        focal = (ch / 2.0) / math.tan(fov / 2.0)
        gl.glUseProgram(self.prog_grid)
        gl.glUniform3f(self.u_grid["u_fwd"], float(fwd[0]), float(fwd[1]), float(fwd[2]))
        gl.glUniform3f(self.u_grid["u_right"], float(right[0]), float(right[1]), float(right[2]))
        gl.glUniform3f(self.u_grid["u_cam_up"], float(cam_up[0]), float(cam_up[1]), float(cam_up[2]))
        gl.glUniform1f(self.u_grid["u_tan_x"], float((cw / 2.0) / focal))
        gl.glUniform1f(self.u_grid["u_tan_y"], float((ch / 2.0) / focal))
        gl.glBindVertexArray(self.vao_grid)
        gl.glDrawArrays(gl.LINES, 0, self.n_grid_verts)

    def draw_telescopic_sun(self, sx, sy, r_sun_exact, cw, ch):
        r_sun = max(4.0, r_sun_exact)
        halo_mult = 3.8 if r_sun < 20.0 else 2.5
        halo_r = min(max(r_sun * halo_mult, 22.0), float(max(cw, ch)))

        x0 = max(0.0, sx - halo_r)
        x1 = min(float(cw), sx + halo_r + 1.0)
        y0 = max(0.0, sy - halo_r)
        y1 = min(float(ch), sy + halo_r + 1.0)
        if x1 <= x0 or y1 <= y0:
            return

        gl = self.gl
        self._upload_screen_rect(x0, y0, x1, y1, cw, ch)
        gl.glUseProgram(self.prog_sun)
        gl.glUniform1f(self.u_sun["u_sx"], float(sx))
        gl.glUniform1f(self.u_sun["u_sy"], float(sy))
        gl.glUniform1f(self.u_sun["u_r_sun"], float(r_sun))
        gl.glUniform1f(self.u_sun["u_halo_mult"], float(halo_mult))
        gl.glUniform1f(self.u_sun["u_ch"], float(ch))
        gl.glBindVertexArray(self.vao_sun)
        gl.glDrawArrays(gl.TRIANGLE_STRIP, 0, 4)

    def draw_telescopic_earth(self, ex, ey, r_earth_exact, cw, ch,
                              cam_right, cam_up, dir_earth_enu, sun_from_earth_enu,
                              moon_from_earth_enu, sun_dist_km,
                              ecef_axes_enu, cloud_offset,
                              eclipse_ring_factor=0.0, dark_side_exposure=1.0):
        r_earth = max(6.5, r_earth_exact)
        pad = max(4.0, r_earth * 0.14)
        r_outer = r_earth + pad

        x0 = max(0.0, ex - r_outer)
        x1 = min(float(cw), ex + r_outer + 1.0)
        y0 = max(0.0, ey - r_outer)
        y1 = min(float(ch), ey + r_outer + 1.0)
        if x1 <= x0 or y1 <= y0:
            return

        e_z_cam = -dir_earth_enu
        e_x_cam = cam_right - np.dot(cam_right, e_z_cam) * e_z_cam
        nx_norm = np.linalg.norm(e_x_cam)
        if nx_norm < 1e-6:
            e_x_cam = -np.cross(cam_up, e_z_cam)
            nx_norm = np.linalg.norm(e_x_cam)
        e_x_cam /= nx_norm

        e_y_cam = cam_up - np.dot(cam_up, e_z_cam) * e_z_cam
        e_y_cam -= np.dot(e_y_cam, e_x_cam) * e_x_cam
        ny_norm = np.linalg.norm(e_y_cam)
        if ny_norm < 1e-6:
            e_y_cam = -np.cross(e_z_cam, e_x_cam)
            ny_norm = np.linalg.norm(e_y_cam)
        e_y_cam /= ny_norm

        x_ecef, y_ecef, z_ecef = ecef_axes_enu
        texels_per_px = self.night_base_w / max(1.0, 2.0 * math.pi * r_earth)
        night_lod = float(np.clip(math.log2(max(1.0, texels_per_px)), 0.0, float(self.night_max_mip)))

        gl = self.gl
        gl.glActiveTexture(gl.TEXTURE0)
        gl.glBindTexture(gl.TEXTURE_2D, self.tex_earth_day)
        gl.glActiveTexture(gl.TEXTURE0 + 1)
        gl.glBindTexture(gl.TEXTURE_2D, self.tex_earth_night)
        gl.glActiveTexture(gl.TEXTURE0 + 2)
        gl.glBindTexture(gl.TEXTURE_2D, self.tex_earth_clouds)

        self._upload_screen_rect(x0, y0, x1, y1, cw, ch)
        gl.glUseProgram(self.prog_earth)
        u = self.u_earth
        gl.glUniform1f(u["u_ex"], float(ex))
        gl.glUniform1f(u["u_ey"], float(ey))
        gl.glUniform1f(u["u_r_earth"], float(r_earth))
        gl.glUniform1f(u["u_ch"], float(ch))
        gl.glUniform3f(u["u_e_x_cam"], float(e_x_cam[0]), float(e_x_cam[1]), float(e_x_cam[2]))
        gl.glUniform3f(u["u_e_y_cam"], float(e_y_cam[0]), float(e_y_cam[1]), float(e_y_cam[2]))
        gl.glUniform3f(u["u_e_z_cam"], float(e_z_cam[0]), float(e_z_cam[1]), float(e_z_cam[2]))
        gl.glUniform3f(u["u_x_ecef"], float(x_ecef[0]), float(x_ecef[1]), float(x_ecef[2]))
        gl.glUniform3f(u["u_y_ecef"], float(y_ecef[0]), float(y_ecef[1]), float(y_ecef[2]))
        gl.glUniform3f(u["u_z_ecef"], float(z_ecef[0]), float(z_ecef[1]), float(z_ecef[2]))
        gl.glUniform3f(u["u_sun_from_earth_enu"], float(sun_from_earth_enu[0]), float(sun_from_earth_enu[1]), float(sun_from_earth_enu[2]))
        gl.glUniform3f(u["u_moon_from_earth_enu"], float(moon_from_earth_enu[0]), float(moon_from_earth_enu[1]), float(moon_from_earth_enu[2]))
        gl.glUniform1f(u["u_moon_sun_dot"], float(np.dot(moon_from_earth_enu, sun_from_earth_enu)))
        gl.glUniform1f(u["u_sun_dist_km"], float(sun_dist_km))
        gl.glUniform1f(u["u_cloud_offset"], float(cloud_offset))
        gl.glUniform1f(u["u_eclipse_ring_factor"], float(eclipse_ring_factor))
        gl.glUniform1f(u["u_dark_side_exposure"], float(dark_side_exposure))
        gl.glUniform1i(u["u_has_day"], 1 if self.has_day else 0)
        gl.glUniform1i(u["u_has_night"], 1 if self.has_night else 0)
        gl.glUniform1i(u["u_has_clouds"], 1 if self.has_clouds else 0)
        gl.glUniform1f(u["u_night_lod"], night_lod)
        gl.glUniform1i(u["u_tex_day"], 0)
        gl.glUniform1i(u["u_tex_night"], 1)
        gl.glUniform1i(u["u_tex_clouds"], 2)

        gl.glBindVertexArray(self.vao_earth)
        gl.glDrawArrays(gl.TRIANGLE_STRIP, 0, 4)

    def draw_hud(self):
        if self.hud_surface is None or not self.tex_hud:
            return
        gl = self.gl
        gl.glActiveTexture(gl.TEXTURE0)
        gl.glBindTexture(gl.TEXTURE_2D, self.tex_hud)
        gl.glUseProgram(self.prog_hud)
        gl.glUniform1i(self.u_hud_tex, 0)
        gl.glBindVertexArray(self.vao_hud)
        gl.glDrawArrays(gl.TRIANGLE_STRIP, 0, 4)


class LunarTerrain3D:
    """
    Silnik terenu Księżyca w architekturze PQS (Procedural QuadSphere / GPU Displacement):
    - Globalna mapa wysokości DEM (GL_R32F) i tekstura powierzchni (GL_RGB8 + mipmapy) siedzą na stałe w VRAM.
    - Jedna statyczna paczka wierzchołków (16x16 komórek + pionowe krawędzie „skirts”) renderowana jest
      w jednym wywołaniu glDrawElementsInstanced (~10 KB transferu danych na klatkę).
    - Vertex Shader przemieszcza wierzchołki z interpolacją Catmull-Rom w lokalnym układzie ENU
      (brak drgań float32 nawet 2 m nad powierzchnią).
    - Fragment Shader oblicza normalne per-pixel z DEM, nakłada wielooktawowy mikro-relief regolitu
      i cieniuje powierzchnię modelem rozpraszania Lommel-Seeliger / Hapke.
    """

    PATCH_N = 16          # Rozdzielczość statycznej paczki: 16x16 komórek = 512 trójkątów/paczkę
    TAU_PX = 3.8          # Docelowy rozmiar wielokąta na ekranie [px]
    MAX_PATCHES = 720     # Budżet paczek na klatkę (720 * 512 = 368 640 trójkątów w 1 draw callu)
    N_HOR_RAYS = 480

    _TERRAIN_VS = """
    #version 330 core
    const float PI = 3.14159265358979323846;
    const float TWO_PI = 6.28318530717958647692;
    const float R_MOON = 1737.4;

    // Atrybuty statycznej siatki paczki (per-vertex)
    in vec2 in_uv;
    in float in_is_skirt;

    // Atrybuty instancji paczki (per-instance)
    in vec4 in_lat_lon;   // (lat0_rad, lat1_rad, lon0_rad, lon1_rad)
    in float in_skirt_km;

    uniform sampler2D u_tex_dem;
    uniform vec2 u_dem_size;

    uniform float u_obs_lat;
    uniform float u_obs_lon;
    uniform float u_obs_elev;
    uniform float u_sin_obs_lat;
    uniform float u_cos_obs_lat;

    uniform vec3 u_fwd;
    uniform vec3 u_right;
    uniform vec3 u_cam_up;
    uniform float u_tan_x;
    uniform float u_tan_y;
    uniform float u_near;
    uniform float u_far;

    out vec2 v_lat_lon;
    out vec3 v_pos_enu;
    out vec3 v_u_pt;
    out vec3 v_north_pt;
    out vec3 v_east_pt;
    out float v_dist_km;

    // Gładka interpolacja bikubiczna Catmull-Rom na teksturze DEM
    float sample_dem_catmull(vec2 uv) {
        vec2 texel = uv * u_dem_size - 0.5;
        vec2 f = fract(texel);
        vec2 i = floor(texel) + 0.5;
        vec2 inv_sz = 1.0 / u_dem_size;

        vec2 f2 = f * f;
        vec2 f3 = f2 * f;
        vec2 w0 = -0.5 * f + f2 - 0.5 * f3;
        vec2 w1 = 1.0 - 2.5 * f2 + 1.5 * f3;
        vec2 w2 = 0.5 * f + 2.0 * f2 - 1.5 * f3;
        vec2 w3 = -0.5 * f2 + 0.5 * f3;

        float h = 0.0;
        for (int r = -1; r <= 2; ++r) {
            float wy = (r == -1) ? w0.y : ((r == 0) ? w1.y : ((r == 1) ? w2.y : w3.y));
            float vy = clamp((i.y + float(r)) * inv_sz.y, 0.5 * inv_sz.y, 1.0 - 0.5 * inv_sz.y);
            float h_row =
                texture(u_tex_dem, vec2((i.x - 1.0) * inv_sz.x, vy)).r * w0.x +
                texture(u_tex_dem, vec2((i.x + 0.0) * inv_sz.x, vy)).r * w1.x +
                texture(u_tex_dem, vec2((i.x + 1.0) * inv_sz.x, vy)).r * w2.x +
                texture(u_tex_dem, vec2((i.x + 2.0) * inv_sz.x, vy)).r * w3.x;
            h += h_row * wy;
        }
        return h;
    }

    void main() {
        float lat = mix(in_lat_lon.x, in_lat_lon.y, in_uv.y);
        float lon = mix(in_lat_lon.z, in_lat_lon.w, in_uv.x);

        vec2 uv_global = vec2((lon + PI) / TWO_PI, (PI * 0.5 - lat) / PI);
        float h = sample_dem_catmull(uv_global) - in_is_skirt * in_skirt_km;

        float dlat = lat - u_obs_lat;
        float dlon = lon - u_obs_lon;
        float sin_lat = sin(lat);
        float cos_lat = cos(lat);
        float sin_dlat = sin(dlat);
        float sin_dlon = sin(dlon);
        float sin_half_dlat = sin(0.5 * dlat);
        float sin_half_dlon = sin(0.5 * dlon);

        // Precyzyjny wektor różnicy jednostkowej u_pt - u_obs w układzie ENU obserwatora
        float du_north = sin_dlat + 2.0 * cos_lat * u_sin_obs_lat * (sin_half_dlon * sin_half_dlon);
        float du_east  = cos_lat * sin_dlon;
        float du_up    = -2.0 * (sin_half_dlat * sin_half_dlat)
                         - 2.0 * cos_lat * u_cos_obs_lat * (sin_half_dlon * sin_half_dlon);

        float r_pt = R_MOON + h;
        vec3 rel_enu = r_pt * vec3(du_north, du_east, du_up) + vec3(0.0, 0.0, h - u_obs_elev);

        // Lokalna baza sferyczna w punkcie terenu (w układzie ENU obserwatora)
        vec3 u_pt = normalize(vec3(du_north, du_east, 1.0 + du_up));
        vec3 east_pt = normalize(vec3(-u_sin_obs_lat * sin_dlon, cos(dlon), u_cos_obs_lat * sin_dlon));
        vec3 north_pt = cross(u_pt, east_pt);

        float zc = dot(rel_enu, u_fwd);
        float xc = dot(rel_enu, u_right);
        float yc = dot(rel_enu, u_cam_up);

        float x_ndc = xc / u_tan_x;
        float y_ndc = yc / u_tan_y;
        float z_log = 2.0 * (log2(max(1e-6, zc / u_near)) / log2(u_far / u_near)) - 1.0;
        gl_Position = vec4(x_ndc, y_ndc, z_log * zc, zc);

        v_lat_lon = vec2(lat, lon);
        v_pos_enu = rel_enu;
        v_u_pt = u_pt;
        v_north_pt = north_pt;
        v_east_pt = east_pt;
        v_dist_km = length(rel_enu);
    }
    """

    _TERRAIN_FS = """
    #version 330 core
    const float PI = 3.14159265358979323846;
    const float TWO_PI = 6.28318530717958647692;
    const float R_MOON = 1737.4;

    in vec2 v_lat_lon;
    in vec3 v_pos_enu;
    in vec3 v_u_pt;
    in vec3 v_north_pt;
    in vec3 v_east_pt;
    in float v_dist_km;

    uniform sampler2D u_tex_dem;
    uniform sampler2D u_tex_albedo;
    uniform vec2 u_dem_size;
    uniform int u_albedo_raw_u8;
    uniform float u_albedo_scale;

    uniform vec3 u_sun_enu;
    uniform vec3 u_earth_enu;
    uniform float u_sun_effective_vis;
    uniform float u_earthshine;
    uniform vec3 u_tint;
    uniform vec3 u_wire_add;
    uniform float u_focal;

    out vec4 out_color;

    // Szybki 3D hash i szum gradientowy bez artefaktów siatki
    float hash31(vec3 p) {
        p = fract(p * vec3(0.1031, 0.1030, 0.0973));
        p += dot(p, p.yxz + 33.33);
        return fract((p.x + p.y) * p.z);
    }

    float noise3d(vec3 p) {
        vec3 i = floor(p);
        vec3 f = fract(p);
        vec3 u = f * f * (3.0 - 2.0 * f);

        float n000 = hash31(i + vec3(0.0, 0.0, 0.0));
        float n100 = hash31(i + vec3(1.0, 0.0, 0.0));
        float n010 = hash31(i + vec3(0.0, 1.0, 0.0));
        float n110 = hash31(i + vec3(1.0, 1.0, 0.0));
        float n001 = hash31(i + vec3(0.0, 0.0, 1.0));
        float n101 = hash31(i + vec3(1.0, 0.0, 1.0));
        float n011 = hash31(i + vec3(0.0, 1.0, 1.0));
        float n111 = hash31(i + vec3(1.0, 1.0, 1.0));

        float nx00 = mix(n000, n100, u.x);
        float nx10 = mix(n010, n110, u.x);
        float nx01 = mix(n001, n101, u.x);
        float nx11 = mix(n011, n111, u.x);

        return mix(mix(nx00, nx10, u.y), mix(nx01, nx11, u.y), u.z);
    }

    // Proceduralna funkcja mikro-kraterów komórkowych (KSP PQS crater noise)
    float micro_crater(vec3 p) {
        vec3 i = floor(p);
        vec3 f = fract(p);
        float min_d = 1.5;
        for (int z = -1; z <= 1; ++z) {
            for (int y = -1; y <= 1; ++y) {
                for (int x = -1; x <= 1; ++x) {
                    vec3 g = vec3(float(x), float(y), float(z));
                    vec3 rnd = vec3(
                        hash31(i + g),
                        hash31(i + g + vec3(17.3, 9.1, 4.7)),
                        hash31(i + g + vec3(5.2, 23.8, 11.4))
                    );
                    vec3 r = g + rnd - f;
                    float d = length(r);
                    min_d = min(min_d, d);
                }
            }
        }
        float rad = 0.44;
        if (min_d < rad) {
            float t = min_d / rad;
            return -0.65 * (1.0 - t * t);
        } else if (min_d < rad * 1.32) {
            float t = (min_d - rad) / (rad * 0.32);
            return 0.22 * sin(t * PI);
        }
        return 0.0;
    }

    // Wysokość mikro-reliefu regolitu w metrach dla dowolnego punktu na sferze
    float regolith_height_m(vec3 p_m, float w_macro, float w_med, float w_fine) {
        float h = 0.0;
        if (w_macro > 0.001) {
            float c1 = micro_crater(p_m * 0.0045);
            float n1 = noise3d(p_m * 0.012) - 0.5;
            h += w_macro * (4.2 * c1 + 2.4 * n1);
        }
        if (w_med > 0.001) {
            float c2 = micro_crater(p_m * 0.042);
            float n2 = noise3d(p_m * 0.085) - 0.5;
            h += w_med * (0.48 * c2 + 0.32 * n2);
        }
        if (w_fine > 0.001) {
            float n3 = noise3d(p_m * 0.75) - 0.5;
            float n4 = noise3d(p_m * 2.8) - 0.5;
            h += w_fine * (0.045 * n3 + 0.018 * n4);
        }
        return h;
    }

    void main() {
        float lat = v_lat_lon.x;
        float lon = v_lat_lon.y;
        vec2 uv_cont = vec2((lon + PI) / TWO_PI, (PI * 0.5 - lat) / PI);
        vec2 uv_wrap = vec2(fract(uv_cont.x), clamp(uv_cont.y, 0.0, 1.0));

        // 1. Próbkowanie tekstury albedo 8K z ciągłymi pochodnymi (brak szwu na południku 180°)
        vec2 d_uv_dx = dFdx(uv_cont);
        vec2 d_uv_dy = dFdy(uv_cont);
        vec3 tex_alb = textureGrad(u_tex_albedo, uv_wrap, d_uv_dx, d_uv_dy).rgb;
        vec3 albedo = (u_albedo_raw_u8 == 1)
            ? (0.055 + 0.22 * pow(tex_alb, vec3(1.15)))
            : (tex_alb * u_albedo_scale);

        // 2. Normalna makroskopowa bezpośrednio z tekstury DEM (per-pixel)
        vec2 inv_dem = 1.0 / u_dem_size;
        float cos_lat = max(0.05, cos(lat));
        float step_u = inv_dem.x;
        float step_v = inv_dem.y;

        float h_e1 = texture(u_tex_dem, uv_wrap + vec2(step_u, 0.0)).r;
        float h_e0 = texture(u_tex_dem, uv_wrap - vec2(step_u, 0.0)).r;
        float h_n1 = texture(u_tex_dem, vec2(uv_wrap.x, clamp(uv_wrap.y - step_v, 0.0, 1.0))).r;
        float h_n0 = texture(u_tex_dem, vec2(uv_wrap.x, clamp(uv_wrap.y + step_v, 0.0, 1.0))).r;

        float dx_km = 2.0 * step_u * TWO_PI * R_MOON * cos_lat;
        float dy_km = 2.0 * step_v * PI * R_MOON;
        float grad_e = ((h_e1 - h_e0) / max(1e-5, dx_km)) * 1.45;
        float grad_n = ((h_n1 - h_n0) / max(1e-5, dy_km)) * 1.45;

        // 3. Wielooktawowy mikro-relief regolitu i ziarno HD (wygaszane z odległością bez aliasingu)
        float dist_m = max(1.0, v_dist_km * 1000.0);
        float m_per_px = dist_m / max(1.0, u_focal);

        float w_macro = clamp(1.0 - smoothstep(25.0, 180.0, m_per_px), 0.0, 1.0);
        float w_med   = clamp(1.0 - smoothstep(2.5, 22.0, m_per_px), 0.0, 1.0);
        float w_fine  = clamp(1.0 - smoothstep(0.18, 1.8, m_per_px), 0.0, 1.0);

        vec3 u_n = normalize(v_u_pt);
        vec3 e_n = normalize(v_east_pt);
        vec3 n_n = normalize(v_north_pt);
        vec3 p_m = u_n * (R_MOON * 1000.0);

        if (w_macro > 0.001) {
            float eps = clamp(m_per_px * 0.65, 0.08, 12.0);
            float h0 = regolith_height_m(p_m, w_macro, w_med, w_fine);
            float he = regolith_height_m(p_m + e_n * eps, w_macro, w_med, w_fine);
            float hn = regolith_height_m(p_m + n_n * eps, w_macro, w_med, w_fine);
            grad_e += (he - h0) / eps;
            grad_n += (hn - h0) / eps;

            // Ziarno i kontrast mineralny regolitu (jasny pył vs ciemniejsze okruchy bazaltowe)
            float grain = (noise3d(p_m * 0.035) - 0.5) * 0.14 * w_macro
                        + (noise3d(p_m * 0.45) - 0.5) * 0.18 * w_med
                        + (noise3d(p_m * 3.6) - 0.5) * 0.22 * w_fine;
            albedo *= clamp(1.0 + grain, 0.68, 1.38);
        }

        vec3 N = normalize(u_n - grad_e * e_n - grad_n * n_n);

        // 4. Fizyczny model rozpraszania regolitu (Lommel-Seeliger + Lambert)
        vec3 V = normalize(-v_pos_enu);
        float mu0 = max(0.0, dot(N, u_sun_enu));
        float mu  = max(0.02, dot(N, V));
        float lommel = (2.0 * mu0) / max(0.08, mu0 + mu);
        float lambert = pow(mu0, 0.85);
        float direct = mix(lambert, lommel, 0.52) * u_sun_effective_vis;

        // Subtelne oświetlenie światłem popielatym Ziemi (zależne od orientacji względem Ziemi)
        float earth_facing = 0.35 + 0.65 * max(0.0, dot(N, u_earth_enu));
        float ambient = 0.028 + u_earthshine * earth_facing;

        float base_light = 165.0 * ambient + 935.0 * direct;
        vec3 lit = clamp(albedo * base_light * u_tint, 4.0, 250.0) / 255.0;
        out_color = vec4(clamp(lit + u_wire_add, 0.0, 1.0), 1.0);
    }
    """

    _HORIZON_VS = """
    #version 330 core
    in vec3 in_enu;
    uniform vec3 u_fwd;
    uniform vec3 u_right;
    uniform vec3 u_cam_up;
    uniform float u_tan_x;
    uniform float u_tan_y;
    void main() {
        float zc = dot(in_enu, u_fwd);
        float xc = dot(in_enu, u_right);
        float yc = dot(in_enu, u_cam_up);
        gl_Position = vec4(xc / u_tan_x, yc / u_tan_y, 0.0, zc);
    }
    """

    _HORIZON_FS = """
    #version 330 core
    out vec4 out_color;
    void main() {
        out_color = vec4(90.0 / 255.0, 175.0 / 255.0, 220.0 / 255.0, 1.0);
    }
    """

    def __init__(self, dem_km: np.ndarray, albedo_rgb: np.ndarray, gl: GL33 = None):
        self.dem = dem_km
        self.H, self.W = dem_km.shape
        self.albedo_map = albedo_rgb
        self.AH, self.AW = albedo_rgb.shape[:2]
        self.albedo_is_u8 = albedo_rgb.dtype == np.uint8

        H = self.H
        self.lat_e = np.empty(H + 2, dtype=np.float64)
        self.lat_e[0] = 90.0
        self.lat_e[1:H + 1] = 90.0 - (np.arange(H) + 0.5) * 180.0 / H
        self.lat_e[H + 1] = -90.0
        self._re_axis = np.arange(H + 2, dtype=np.float64)
        self.pole_h = (float(np.mean(dem_km[0], dtype=np.float64)), float(np.mean(dem_km[H - 1], dtype=np.float64)))

        # Profil horyzontu topograficznego 360°
        self.az_grid = np.linspace(0.0, 2.0 * np.pi, 721)
        self.n_az = len(self.az_grid) - 1

        # Korzenie globalnego drzewa czwórkowego PQS (8 pasów lat x 16 pasów lon = 128 węzłów bazowych)
        root_lats = np.linspace(0.5 * math.pi, -0.5 * math.pi, 9)
        root_lons = np.linspace(-math.pi, math.pi, 17)
        r_lat0 = np.repeat(root_lats[:-1], 16)
        r_lat1 = np.repeat(root_lats[1:], 16)
        r_lon0 = np.tile(root_lons[:-1], 8)
        r_lon1 = np.tile(root_lons[1:], 8)
        self._roots = (r_lat0, r_lat1, r_lon0, r_lon1)

        self.cached_lat = None
        self.cached_lon = None
        self.cached_eye_height_m = None
        self.horizon_alt = None
        self.horizon_dist_km = None
        self.horizon_lat = None
        self.horizon_lon = None
        self.horizon_elev_km = None
        self.obs_elev_km = 0.0
        self.obs_radius_km = R_MOON
        self.eye_km = 0.002
        self.r_max_km = 450.0
        self.up0 = np.array([0.0, 0.0, 1.0])
        self.east0 = np.array([0.0, 1.0, 0.0])
        self.north0 = np.array([1.0, 0.0, 0.0])
        self.obs_body = np.array([0.0, 0.0, R_MOON])
        self.quad_count = 0
        self.drawn_count = 0
        self.lod_tau = self.TAU_PX
        self.lod_tau_used = self.TAU_PX

        self.gl = gl
        self._gpu_ready = False
        if self.gl is not None:
            self._init_gpu(self.gl)

    def _build_static_patch_geometry(self):
        """Tworzy statyczną siatkę paczki (PATCH_N x PATCH_N) wraz z pionowymi krawędziami (skirts)."""
        N = self.PATCH_N
        u_lin = np.linspace(0.0, 1.0, N + 1, dtype=np.float32)
        v_lin = np.linspace(0.0, 1.0, N + 1, dtype=np.float32)
        uu, vv = np.meshgrid(u_lin, v_lin)

        # Wierzchołki główne paczki: (N+1) x (N+1)
        core_verts = np.column_stack([uu.ravel(), vv.ravel(), np.zeros((N + 1) ** 2, dtype=np.float32)])

        # Indeksy trójkątów głównych (CCW widziane z góry: +u = wschód, +v = południe)
        r = np.arange(N, dtype=np.uint32)[:, None]
        c = np.arange(N, dtype=np.uint32)[None, :]
        stride = N + 1
        i00 = r * stride + c
        i10 = (r + 1) * stride + c
        i11 = (r + 1) * stride + (c + 1)
        i01 = r * stride + (c + 1)
        core_tris = np.stack([i00, i10, i11, i00, i11, i01], axis=-1).ravel()
        core_wire = np.stack([i00, i01, i00, i10], axis=-1).ravel()

        # 4 krawędzie „spódnic” (skirts) zakrywające ewentualne szwy między poziomami LOD
        verts_list = [core_verts]
        tris_list = [core_tris]
        offset = len(core_verts)

        # Definicja 4 brzegów w kolejności zgodnej z nawijaniem na zewnątrz:
        # 1) Górny (v=0, u: 0->1), 2) Prawy (u=1, v: 0->1), 3) Dolny (v=1, u: 1->0), 4) Lewy (u=0, v: 1->0)
        edges = [
            (u_lin, np.zeros_like(u_lin), np.arange(N + 1, dtype=np.uint32)),
            (np.ones_like(v_lin), v_lin, np.arange(N + 1, dtype=np.uint32) * stride + N),
            (u_lin[::-1], np.ones_like(u_lin), N * stride + np.arange(N, -1, -1, dtype=np.uint32)),
            (np.zeros_like(v_lin), v_lin[::-1], np.arange(N, -1, -1, dtype=np.uint32) * stride),
        ]
        for eu, ev, top_idx in edges:
            sv = np.column_stack([eu, ev, np.ones(N + 1, dtype=np.float32)])
            bot_idx = offset + np.arange(N + 1, dtype=np.uint32)
            t0 = top_idx[:-1]
            t1 = top_idx[1:]
            b0 = bot_idx[:-1]
            b1 = bot_idx[1:]
            edge_tris = np.stack([t0, t1, b1, t0, b1, b0], axis=-1).ravel()
            verts_list.append(sv)
            tris_list.append(edge_tris)
            offset += N + 1

        verts = np.ascontiguousarray(np.vstack(verts_list), dtype=np.float32)
        tris = np.ascontiguousarray(np.concatenate(tris_list), dtype=np.uint32)
        wire = np.ascontiguousarray(core_wire, dtype=np.uint32)
        return verts, tris, wire

    def _init_gpu(self, gl: GL33):
        self.gl = gl
        self._prog_terrain = gl.create_program(self._TERRAIN_VS, self._TERRAIN_FS)
        self._prog_horizon = gl.create_program(self._HORIZON_VS, self._HORIZON_FS)

        # 1. Wgranie globalnej mapy wysokości DEM (GL_R32F) do VRAM
        self._tex_dem = gl.gen_texture()
        gl.glBindTexture(gl.TEXTURE_2D, self._tex_dem)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
        c_dem = np.ascontiguousarray(self.dem, dtype=np.float32)
        gl.glTexImage2D(
            gl.TEXTURE_2D, 0, gl.R32F, self.W, self.H, 0, gl.RED, gl.FLOAT, c_dem.ctypes.data_as(ctypes.c_void_p)
        )
        del c_dem

        # 2. Wgranie tekstury powierzchni Księżyca (do 8K) z mipmapami do VRAM
        self._tex_albedo = gl.gen_texture()
        gl.glBindTexture(gl.TEXTURE_2D, self._tex_albedo)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR)
        gl.glTexParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
        if self.albedo_is_u8:
            c_alb = np.ascontiguousarray(self.albedo_map, dtype=np.uint8)
            self._albedo_scale = 1.0
        else:
            self._albedo_scale = 0.40
            c_alb = np.ascontiguousarray(
                np.clip(self.albedo_map / self._albedo_scale * 255.0, 0.0, 255.0), dtype=np.uint8
            )
        gl.glTexImage2D(
            gl.TEXTURE_2D, 0, gl.RGB8, self.AW, self.AH, 0, gl.RGB, gl.UNSIGNED_BYTE, c_alb.ctypes.data_as(ctypes.c_void_p)
        )
        gl.glGenerateMipmap(gl.TEXTURE_2D)
        del c_alb

        # 3. Statyczny bufor paczki + bufor instancji (10 KB/klatkę)
        patch_verts, patch_tris, patch_wire = self._build_static_patch_geometry()
        self._n_patch_tris = len(patch_tris)
        self._n_patch_wire = len(patch_wire)

        self._vao_terrain = gl.gen_vao()
        gl.glBindVertexArray(self._vao_terrain)

        self._vbo_patch = gl.gen_buffer()
        gl.glBindBuffer(gl.ARRAY_BUFFER, self._vbo_patch)
        gl.glBufferData(gl.ARRAY_BUFFER, patch_verts.nbytes, patch_verts.ctypes.data_as(ctypes.c_void_p), gl.STATIC_DRAW)

        loc_uv = gl.glGetAttribLocation(self._prog_terrain, b"in_uv")
        loc_skirt = gl.glGetAttribLocation(self._prog_terrain, b"in_is_skirt")
        gl.glEnableVertexAttribArray(loc_uv)
        gl.glVertexAttribPointer(loc_uv, 2, gl.FLOAT, 0, 12, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(loc_skirt)
        gl.glVertexAttribPointer(loc_skirt, 1, gl.FLOAT, 0, 12, ctypes.c_void_p(8))

        self._vbo_instances = gl.gen_buffer()
        self._inst_buf = np.empty((self.MAX_PATCHES, 5), dtype=np.float32)
        gl.glBindBuffer(gl.ARRAY_BUFFER, self._vbo_instances)
        gl.glBufferData(gl.ARRAY_BUFFER, self._inst_buf.nbytes, None, gl.DYNAMIC_DRAW)

        loc_ll = gl.glGetAttribLocation(self._prog_terrain, b"in_lat_lon")
        loc_sk_km = gl.glGetAttribLocation(self._prog_terrain, b"in_skirt_km")
        gl.glEnableVertexAttribArray(loc_ll)
        gl.glVertexAttribPointer(loc_ll, 4, gl.FLOAT, 0, 20, ctypes.c_void_p(0))
        gl.glVertexAttribDivisor(loc_ll, 1)
        gl.glEnableVertexAttribArray(loc_sk_km)
        gl.glVertexAttribPointer(loc_sk_km, 1, gl.FLOAT, 0, 20, ctypes.c_void_p(16))
        gl.glVertexAttribDivisor(loc_sk_km, 1)

        self._ibo_tris = gl.gen_buffer()
        gl.glBindBuffer(gl.ELEMENT_ARRAY_BUFFER, self._ibo_tris)
        gl.glBufferData(gl.ELEMENT_ARRAY_BUFFER, patch_tris.nbytes, patch_tris.ctypes.data_as(ctypes.c_void_p), gl.STATIC_DRAW)

        self._ibo_wire = gl.gen_buffer()
        gl.glBindBuffer(gl.ELEMENT_ARRAY_BUFFER, self._ibo_wire)
        gl.glBufferData(gl.ELEMENT_ARRAY_BUFFER, patch_wire.nbytes, patch_wire.ctypes.data_as(ctypes.c_void_p), gl.STATIC_DRAW)

        self._u_terrain = {
            name: gl.glGetUniformLocation(self._prog_terrain, name.encode("ascii"))
            for name in (
                "u_tex_dem", "u_tex_albedo", "u_dem_size",
                "u_albedo_raw_u8", "u_albedo_scale",
                "u_obs_lat", "u_obs_lon", "u_obs_elev",
                "u_sin_obs_lat", "u_cos_obs_lat",
                "u_fwd", "u_right", "u_cam_up",
                "u_tan_x", "u_tan_y", "u_near", "u_far",
                "u_sun_enu", "u_earth_enu", "u_sun_effective_vis",
                "u_earthshine", "u_tint", "u_wire_add", "u_focal",
            )
        }

        self._vao_horizon = gl.gen_vao()
        self._vbo_horizon = gl.gen_buffer()
        gl.glBindVertexArray(self._vao_horizon)
        gl.glBindBuffer(gl.ARRAY_BUFFER, self._vbo_horizon)
        gl.glBufferData(gl.ARRAY_BUFFER, len(self.az_grid) * 3 * 4, None, gl.DYNAMIC_DRAW)
        loc_henu = gl.glGetAttribLocation(self._prog_horizon, b"in_enu")
        gl.glEnableVertexAttribArray(loc_henu)
        gl.glVertexAttribPointer(loc_henu, 3, gl.FLOAT, 0, 12, ctypes.c_void_p(0))

        self._u_horizon = {
            name: gl.glGetUniformLocation(self._prog_horizon, name.encode("ascii"))
            for name in ("u_fwd", "u_right", "u_cam_up", "u_tan_x", "u_tan_y")
        }
        self._gpu_ready = True

    # --- Próbkowanie DEM na CPU (dla wysokości obserwatora i profilu horyzontu 360°) ---
    def _lat_to_re(self, lat_deg):
        return np.interp(-np.asarray(lat_deg, dtype=np.float64), -self.lat_e, self._re_axis)

    def _lon_to_c(self, lon_deg):
        return np.mod((np.asarray(lon_deg, dtype=np.float64) + 180.0) * self.W / 360.0 - 0.5, self.W)

    def _node_h(self, re, c):
        r = np.clip(re - 1, 0, self.H - 1)
        h = np.asarray(self.dem[r, c], dtype=np.float64)
        h = np.where(re <= 0, self.pole_h[0], h)
        return np.where(re >= self.H + 1, self.pole_h[1], h)

    def sample_dem_bilinear(self, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
        """Dwuliniowa interpolacja wysokości (km) na bazowej siatce węzłów DEM."""
        fy = self._lat_to_re(lat_deg)
        fx = self._lon_to_c(lon_deg)
        y0 = np.minimum(np.floor(fy).astype(np.int64), self.H)
        x0f = np.floor(fx)
        x0 = x0f.astype(np.int64) % self.W
        x1 = (x0 + 1) % self.W
        y1 = y0 + 1
        wy = fy - y0
        wx = fx - x0f
        return (
            (self._node_h(y0, x0) * (1.0 - wx) + self._node_h(y0, x1) * wx) * (1.0 - wy)
            + (self._node_h(y1, x0) * (1.0 - wx) + self._node_h(y1, x1) * wx) * wy
        )

    @staticmethod
    def horizon_range_km(eye_km: float) -> float:
        """Zasięg terenu/horyzontu: max(450, √(2R(h_oka+12)) + √(2R·12)) km."""
        return max(450.0, math.sqrt(2.0 * R_MOON * (eye_km + 12.0)) + math.sqrt(2.0 * R_MOON * 12.0))

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

        eye_km = eye_height_m / 1000.0
        r_max = self.horizon_range_km(eye_km)
        self.eye_km = eye_km
        self.r_max_km = r_max

        lat0 = math.radians(lat_deg)
        lon0 = math.radians(lon_deg)
        up0 = np.array([math.cos(lat0) * math.cos(lon0), math.cos(lat0) * math.sin(lon0), math.sin(lat0)])
        east0 = np.array([-math.sin(lon0), math.cos(lon0), 0.0])
        north0 = np.cross(up0, east0)
        self.up0, self.east0, self.north0 = up0, east0, north0

        ground_elev = float(self.sample_dem_bilinear(np.array([lat_deg]), np.array([lon_deg]))[0])
        self.obs_elev_km = ground_elev
        self.obs_radius_km = R_MOON + ground_elev + eye_km
        obs_body = self.obs_radius_km * up0
        self.obs_body = obs_body

        # Profil horyzontu topograficznego 360° (720 azymutów x 480 promieni do r_max)
        hor_radii_km = np.geomspace(0.015, r_max, self.N_HOR_RAYS)
        delta_h = (hor_radii_km / R_MOON)[:, None]
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

    def _camera_body(self, cam_alt, cam_az):
        """Baza kamery (fwd, right, up) w układzie [North, East, Up] oraz w układzie ciała."""
        fwd = np.array([math.cos(cam_alt) * math.cos(cam_az), math.cos(cam_alt) * math.sin(cam_az), math.sin(cam_alt)])
        right = np.array([-math.sin(cam_az), math.cos(cam_az), 0.0])
        cam_up = np.array([-math.sin(cam_alt) * math.cos(cam_az), -math.sin(cam_alt) * math.sin(cam_az), math.cos(cam_alt)])
        to_body = np.stack([self.north0, self.east0, self.up0], axis=0)
        return fwd, right, cam_up, fwd @ to_body, right @ to_body, cam_up @ to_body

    def _lod_pass(self, focal, tan_x, tan_y, fwd_b, right_b, up_b, tau):
        """Drzewo czwórkowe PQS dobierające paczki instancji (16x16 komórek każda)."""
        up0, obs = self.up0, self.obs_body
        r_max = self.r_max_km
        h2 = self.eye_km * self.eye_km
        inv_x = 1.0 / math.sqrt(1.0 + tan_x * tan_x)
        inv_y = 1.0 / math.sqrt(1.0 + tan_y * tan_y)
        min_cell_rad = (1.5e-4) / R_MOON  # Minimalna komórka ~15 cm (głębia podziału do 18 poziomów)

        lat0, lat1, lon0, lon1 = self._roots
        depth = np.zeros(len(lat0), dtype=np.int32)
        out_lat0, out_lat1, out_lon0, out_lon1, out_skirt = [], [], [], [], []

        while lat0.size:
            dlat = lat0 - lat1
            dlon = lon1 - lon0
            ns = R_MOON * dlat
            cos_eq = np.where((lat0 > 0.0) & (lat1 < 0.0), 1.0, np.maximum(np.cos(lat0), np.cos(lat1)))
            ew = R_MOON * dlon * cos_eq

            latc = 0.5 * (lat0 + lat1)
            lonc = 0.5 * (lon0 + lon1)
            clc = np.cos(latc)
            ux, uy, uz = clc * np.cos(lonc), clc * np.sin(lonc), np.sin(latc)

            arc = R_MOON * np.arccos(np.clip(ux * up0[0] + uy * up0[1] + uz * up0[2], -1.0, 1.0))
            half = 0.5 * np.hypot(ns, ew)
            d_poz = np.maximum(arc - half, 0.0)

            px, py, pz = R_MOON * ux - obs[0], R_MOON * uy - obs[1], R_MOON * uz - obs[2]
            zc = px * fwd_b[0] + py * fwd_b[1] + pz * fwd_b[2]
            xc = px * right_b[0] + py * right_b[1] + pz * right_b[2]
            yc = px * up_b[0] + py * up_b[1] + pz * up_b[2]
            rad = half + R_MOON * (1.0 - np.cos(np.minimum(half / R_MOON, math.pi))) + 14.0

            keep = (
                (d_poz <= r_max)
                & (zc >= -rad)
                & ((zc * tan_x + xc) * inv_x >= -rad)
                & ((zc * tan_x - xc) * inv_x >= -rad)
                & ((zc * tan_y + yc) * inv_y >= -rad)
                & ((zc * tan_y - yc) * inv_y >= -rad)
            )

            d = np.sqrt(d_poz * d_poz + h2)
            cell_size_px = (np.maximum(ns, ew) / self.PATCH_N) * focal / np.maximum(d, 1e-9)

            can_r = dlat > (min_cell_rad * self.PATCH_N)
            can_c = dlon > (min_cell_rad * self.PATCH_N)
            split_r = ~(ew > 1.5 * ns) & can_r
            split_c = ~(ns > 1.5 * ew) & can_c
            stuck = (~split_r & ~split_c) | (depth >= 18)

            leaf = keep & ((cell_size_px <= tau) | stuck)
            if leaf.any():
                out_lat0.append(lat0[leaf])
                out_lat1.append(lat1[leaf])
                out_lon0.append(lon0[leaf])
                out_lon1.append(lon1[leaf])
                skirt = np.clip(0.035 * np.maximum(ns[leaf], ew[leaf]), 0.002, 4.5)
                out_skirt.append(skirt)

            sp = keep & ~leaf
            if not sp.any():
                break

            la0, la1, lo0, lo1 = lat0[sp], lat1[sp], lon0[sp], lon1[sp]
            sr, sc = split_r[sp], split_c[sp]
            dp = depth[sp] + 1
            lam = 0.5 * (la0 + la1)
            lom = 0.5 * (lo0 + lo1)

            n_la0, n_la1, n_lo0, n_lo1, n_dp = [], [], [], [], []
            for dr, dc in ((0, 0), (1, 0), (0, 1), (1, 1)):
                m = np.ones(la0.shape, dtype=bool)
                if dr:
                    m &= sr
                if dc:
                    m &= sc
                if not m.any():
                    continue
                c_la0 = np.where(sr[m], lam[m] if dr else la0[m], la0[m])
                c_la1 = np.where(sr[m], la1[m] if dr else lam[m], la1[m])
                c_lo0 = np.where(sc[m], lom[m] if dc else lo0[m], lo0[m])
                c_lo1 = np.where(sc[m], lo1[m] if dc else lom[m], lo1[m])
                n_la0.append(c_la0)
                n_la1.append(c_la1)
                n_lo0.append(c_lo0)
                n_lo1.append(c_lo1)
                n_dp.append(dp[m])

            if not n_la0:
                break
            lat0 = np.concatenate(n_la0)
            lat1 = np.concatenate(n_la1)
            lon0 = np.concatenate(n_lo0)
            lon1 = np.concatenate(n_lo1)
            depth = np.concatenate(n_dp)

        if not out_lat0:
            empty = np.empty(0, dtype=np.float64)
            return empty, empty, empty, empty, empty

        return (
            np.concatenate(out_lat0),
            np.concatenate(out_lat1),
            np.concatenate(out_lon0),
            np.concatenate(out_lon1),
            np.concatenate(out_skirt),
        )

    def _select_lod(self, cw, ch, cam_alt, cam_az, fov):
        """Wybór paczek LOD dla bieżącej kamery z budżetem MAX_PATCHES."""
        focal = (ch / 2.0) / math.tan(fov / 2.0)
        margin = 90.0
        tan_x = (cw / 2.0 + margin) / focal
        tan_y = (ch / 2.0 + margin) / focal
        _, _, _, fwd_b, right_b, up_b = self._camera_body(cam_alt, cam_az)

        tau = max(self.TAU_PX, self.lod_tau)
        patches = self._lod_pass(focal, tan_x, tan_y, fwd_b, right_b, up_b, tau)
        n = len(patches[0])
        if n > self.MAX_PATCHES:
            tau *= math.sqrt(n / self.MAX_PATCHES)
            patches = self._lod_pass(focal, tan_x, tan_y, fwd_b, right_b, up_b, tau)
            self.lod_tau = tau
        elif n < 0.6 * self.MAX_PATCHES and tau > self.TAU_PX:
            self.lod_tau = max(self.TAU_PX, tau * math.sqrt(max(1, n) / (0.8 * self.MAX_PATCHES)))
        else:
            self.lod_tau = tau

        self.lod_tau_used = tau
        self.quad_count = len(patches[0]) * (self.PATCH_N * self.PATCH_N)
        return patches

    def draw_3d(self, screen, cw, ch, cam_alt, cam_az, fov, sun_alt, sun_az, earth_alt, earth_az=0.0,
                sun_effective_vis=1.0, eclipse_red_glow=0.0,
                wireframe=False, show_horizon_line=True):
        if not self._gpu_ready:
            self._init_gpu(self.gl)

        gl = self.gl
        fwd, right, cam_up, _, _, _ = self._camera_body(cam_alt, cam_az)

        near_z = 0.0002
        far_z = max(2000.0, self.r_max_km * 2.0)
        half_cw = cw / 2.0
        half_ch = ch / 2.0
        focal = half_ch / math.tan(fov / 2.0)
        tan_x = half_cw / focal
        tan_y = half_ch / focal

        la0, la1, lo0, lo1, skirt = self._select_lod(cw, ch, cam_alt, cam_az, fov)
        n_patches = min(len(la0), self.MAX_PATCHES)

        if n_patches > 0:
            inst = self._inst_buf[:n_patches]
            inst[:, 0] = la0[:n_patches]
            inst[:, 1] = la1[:n_patches]
            inst[:, 2] = lo0[:n_patches]
            inst[:, 3] = lo1[:n_patches]
            inst[:, 4] = skirt[:n_patches]

            gl.glBindBuffer(gl.ARRAY_BUFFER, self._vbo_instances)
            gl.glBufferSubData(gl.ARRAY_BUFFER, 0, inst.nbytes, inst.ctypes.data_as(ctypes.c_void_p))

            obs_lat_r = math.radians(self.cached_lat)
            obs_lon_r = math.radians(self.cached_lon)
            obs_total_elev = self.obs_elev_km + self.eye_km

            sun_enu = np.array([
                math.cos(sun_alt) * math.cos(sun_az),
                math.cos(sun_alt) * math.sin(sun_az),
                math.sin(sun_alt),
            ])
            earth_enu = np.array([
                math.cos(earth_alt) * math.cos(earth_az),
                math.cos(earth_alt) * math.sin(earth_az),
                math.sin(earth_alt),
            ])
            earthshine = 0.045 * max(0.0, math.sin(earth_alt))
            tint = (
                1.0 + 0.85 * eclipse_red_glow,
                1.0 - 0.15 * eclipse_red_glow,
                1.0 - 0.35 * eclipse_red_glow,
            )

            gl.glActiveTexture(gl.TEXTURE0)
            gl.glBindTexture(gl.TEXTURE_2D, self._tex_dem)
            gl.glActiveTexture(gl.TEXTURE0 + 1)
            gl.glBindTexture(gl.TEXTURE_2D, self._tex_albedo)

            gl.glUseProgram(self._prog_terrain)
            u = self._u_terrain
            gl.glUniform1i(u["u_tex_dem"], 0)
            gl.glUniform1i(u["u_tex_albedo"], 1)
            gl.glUniform2f(u["u_dem_size"], float(self.W), float(self.H))
            gl.glUniform1i(u["u_albedo_raw_u8"], 1 if self.albedo_is_u8 else 0)
            gl.glUniform1f(u["u_albedo_scale"], float(self._albedo_scale))

            gl.glUniform1f(u["u_obs_lat"], float(obs_lat_r))
            gl.glUniform1f(u["u_obs_lon"], float(obs_lon_r))
            gl.glUniform1f(u["u_obs_elev"], float(obs_total_elev))
            gl.glUniform1f(u["u_sin_obs_lat"], float(math.sin(obs_lat_r)))
            gl.glUniform1f(u["u_cos_obs_lat"], float(math.cos(obs_lat_r)))

            gl.glUniform3f(u["u_fwd"], float(fwd[0]), float(fwd[1]), float(fwd[2]))
            gl.glUniform3f(u["u_right"], float(right[0]), float(right[1]), float(right[2]))
            gl.glUniform3f(u["u_cam_up"], float(cam_up[0]), float(cam_up[1]), float(cam_up[2]))
            gl.glUniform1f(u["u_tan_x"], float(tan_x))
            gl.glUniform1f(u["u_tan_y"], float(tan_y))
            gl.glUniform1f(u["u_near"], float(near_z))
            gl.glUniform1f(u["u_far"], float(far_z))

            gl.glUniform3f(u["u_sun_enu"], float(sun_enu[0]), float(sun_enu[1]), float(sun_enu[2]))
            gl.glUniform3f(u["u_earth_enu"], float(earth_enu[0]), float(earth_enu[1]), float(earth_enu[2]))
            gl.glUniform1f(u["u_sun_effective_vis"], float(sun_effective_vis))
            gl.glUniform1f(u["u_earthshine"], float(earthshine))
            gl.glUniform3f(u["u_tint"], float(tint[0]), float(tint[1]), float(tint[2]))
            gl.glUniform3f(u["u_wire_add"], 0.0, 0.0, 0.0)
            gl.glUniform1f(u["u_focal"], float(focal))

            gl.glEnable(gl.DEPTH_TEST)
            gl.glEnable(gl.CULL_FACE)
            gl.glFrontFace(gl.CCW)
            gl.glDisable(gl.BLEND)

            gl.glBindVertexArray(self._vao_terrain)
            gl.glBindBuffer(gl.ELEMENT_ARRAY_BUFFER, self._ibo_tris)
            if wireframe:
                gl.glEnable(gl.POLYGON_OFFSET_FILL)
                gl.glPolygonOffset(1.0, 1.0)
                gl.glDrawElementsInstanced(gl.TRIANGLES, self._n_patch_tris, gl.UNSIGNED_INT, None, n_patches)
                gl.glDisable(gl.POLYGON_OFFSET_FILL)
                gl.glUniform3f(u["u_wire_add"], 35.0 / 255.0, 35.0 / 255.0, 40.0 / 255.0)
                gl.glBindBuffer(gl.ELEMENT_ARRAY_BUFFER, self._ibo_wire)
                gl.glDrawElementsInstanced(gl.LINES, self._n_patch_wire, gl.UNSIGNED_INT, None, n_patches)
            else:
                gl.glDrawElementsInstanced(gl.TRIANGLES, self._n_patch_tris, gl.UNSIGNED_INT, None, n_patches)

            self.drawn_count = n_patches
        else:
            self.drawn_count = 0

        if show_horizon_line and self.horizon_alt is not None:
            ca = np.cos(self.horizon_alt)
            hp = np.ascontiguousarray(
                np.stack([ca * np.cos(self.az_grid), ca * np.sin(self.az_grid), np.sin(self.horizon_alt)], axis=1),
                dtype=np.float32,
            )
            gl.glBindBuffer(gl.ARRAY_BUFFER, self._vbo_horizon)
            gl.glBufferSubData(gl.ARRAY_BUFFER, 0, hp.nbytes, hp.ctypes.data_as(ctypes.c_void_p))

            gl.glDisable(gl.DEPTH_TEST)
            gl.glDisable(gl.CULL_FACE)
            gl.glLineWidth(2.0)
            gl.glUseProgram(self._prog_horizon)
            uh = self._u_horizon
            gl.glUniform3f(uh["u_fwd"], float(fwd[0]), float(fwd[1]), float(fwd[2]))
            gl.glUniform3f(uh["u_right"], float(right[0]), float(right[1]), float(right[2]))
            gl.glUniform3f(uh["u_cam_up"], float(cam_up[0]), float(cam_up[1]), float(cam_up[2]))
            gl.glUniform1f(uh["u_tan_x"], float(tan_x))
            gl.glUniform1f(uh["u_tan_y"], float(tan_y))
            gl.glBindVertexArray(self._vao_horizon)
            gl.glDrawArrays(gl.LINE_STRIP, 0, len(hp))
            gl.glLineWidth(1.0)


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
    R_prec_icrf_to_mod = rot_z(z_a) @ rot_y(-theta_a) @ rot_z(zeta_a)

    gmst = math.radians((280.46061837 + 360.98564736629 * d_j2000) % 360.0)
    R_icrf_to_ecef = rot_z(-gmst) @ R_prec_icrf_to_mod
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
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
    W, H = 1280, 800
    screen = pygame.display.set_mode((W, H), pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE)
    gl = GL33()

    pygame.display.set_caption("Lunar Stellarium - Silnik PQS GPU i Zoom Teleskopowy")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Consolas", 15)
    font_big = pygame.font.SysFont("Consolas", 18, bold=True)

    dem_km, albedo_rgb, dem_source = load_or_download_lunar_maps()
    terrain_3d = LunarTerrain3D(dem_km, albedo_rgb, gl=gl)
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
    last_hud_state = None
    hud_frame_skip = 0

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

    gpu = GPURenderer(
        gl,
        stars_ecl,
        star_mags,
        day_arr=earth_day_arr,
        night_mips=earth_night_mips,
        clouds_arr=earth_clouds_arr,
    )

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
        gl.glViewport(0, 0, cw, ch)
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

        gl.glClearColor(5.0 / 255.0, 7.0 / 255.0, 12.0 / 255.0, 1.0)
        gl.glClear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
        gl.glDisable(gl.DEPTH_TEST)
        gl.glDisable(gl.CULL_FACE)
        gl.glEnable(gl.BLEND)
        gl.glBlendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)

        # 1. Gwiazdy (GPU)
        gpu.draw_stars(R_body, north, east, up, cam_basis, cw, ch, fov)

        # 2. Siatka azymutalna (GPU)
        gpu.draw_grid(cam_basis, cw, ch, fov)

        # 3. SŁOŃCE (GPU shader: pociemnienie brzegowe + korona)
        sun_proj = project_point(sun_alt, sun_az, cw, ch, cam_basis)
        if sun_proj:
            sx, sy, z_cam, focal = sun_proj
            r_sun_exact = math.tan(ang_sun) * focal / z_cam
            gpu.draw_telescopic_sun(sx, sy, r_sun_exact, cw, ch)

        # 4. ZIEMIA (GPU shader + tekstury: orientacja N-S/W-E, obrót W->E, ciemna noc, zaćmienia)
        earth_proj = project_point(earth_alt, earth_az, cw, ch, cam_basis)
        if earth_proj:
            ex, ey, z_cam, focal = earth_proj
            r_earth_exact = math.tan(ang_earth) * focal / z_cam
            d_rel = d_j2000 - year_data["d_j2000_total"][0]
            cloud_offset = (d_rel * 0.015 + anim_time * 0.0012) % 1.0
            gpu.draw_telescopic_earth(
                ex, ey, r_earth_exact, cw, ch,
                cam_right, cam_up, dir_earth_enu, sun_from_earth_enu,
                moon_from_earth_enu, sun_dist_from_earth,
                ecef_axes_enu, cloud_offset,
                eclipse_ring_factor=eclipse_ring_factor,
                dark_side_exposure=dark_side_exposure,
            )

        # 5. MODEL 3D POWIERZCHNI KSIĘŻYCA (PQS GPU INSTANCING + PER-PIXEL REGOLITH SHADER)
        terrain_3d.draw_3d(
            None, cw, ch, cam_alt, cam_az, fov,
            sun_alt, sun_az, earth_alt, earth_az=earth_az,
            sun_effective_vis=sun_effective_vis,
            eclipse_red_glow=eclipse_red_glow,
            wireframe=wireframe_mode,
            show_horizon_line=show_horizon_line,
        )

        # 6. HUD (aktualizowany i wysyłany do VRAM tylko przy zmianie stanu)
        hud_state = (
            cw,
            ch,
            round(slider_time.val, 2),
            round(cam_az, 4),
            round(cam_alt, 4),
            round(fov, 4),
            round(slider_lat.val, 4),
            round(slider_lon.val, 4),
            round(slider_height.val, 1),
            current_year,
            wireframe_mode,
            show_horizon_line,
            status_timer > 0.0,
            terrain_3d.drawn_count,
        )
        hud_frame_skip += 1
        if hud_state != last_hud_state and (not playing or hud_frame_skip >= 2):
            last_hud_state = hud_state
            hud_frame_skip = 0
            hud_surf = gpu.get_hud_surface(cw, ch)

            if sun_proj:
                sx, sy, z_cam, focal = sun_proj
                r_label = max(6, int(math.tan(ang_sun) * focal / z_cam))
                if 0 <= sx + r_label + 6 < cw and 0 <= sy - 8 < ch:
                    hud_surf.blit(font.render("Słońce", True, (255, 230, 150)), (sx + r_label + 6, sy - 8))

            if earth_proj:
                ex, ey, z_cam, focal = earth_proj
                r_elabel = max(8, int(math.tan(ang_earth) * focal / z_cam))
                if 0 <= ex + r_elabel + 8 < cw and 0 <= ey - 8 < ch:
                    hud_surf.blit(font.render("Ziemia", True, (130, 200, 255)), (ex + r_elabel + 8, ey - 8))

            for label, deg in [("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315)]:
                az_r = math.radians(deg)
                h_alt = terrain_3d.get_horizon_at_azimuth(az_r) + max(math.radians(1.2), fov * 0.02)
                proj = project_point(h_alt, az_r, cw, ch, cam_basis)
                if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                    col = (255, 90, 90) if label == "N" else (210, 220, 235)
                    txt = font_big.render(label, True, col)
                    hud_surf.blit(txt, (proj[0] - txt.get_width() // 2, proj[1] - txt.get_height() // 2))

            zoom_mag = base_fov / fov
            height_str = format_height_m(slider_height.val)
            n_tris = terrain_3d.drawn_count * (terrain_3d.PATCH_N * terrain_3d.PATCH_N * 2)

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
                f"Lokacja: {location_name} | DEM: {dem_source} (GPU PQS)",
                f"Teren: {terrain_3d.obs_elev_km:+.3f} km | Wys. obs.: {height_str} | Zoom: {zoom_mag:.1f}x",
                f"Kamera: Az {math.degrees(cam_az):.2f}° | Alt {math.degrees(cam_alt):+.2f}° (Hor: {math.degrees(cam_hor):+.2f}°)",
                f"Siatka GPU: {terrain_3d.drawn_count} paczek ({n_tris:,} trójkątów) | τ {terrain_3d.lod_tau_used:.1f} px",
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
            hud_surf.blit(panel_surf, (cw - panel_w - 15, 15))

            for i, line in enumerate(info_lines):
                hud_surf.blit(font.render(line, True, (210, 215, 225)), (cw - panel_w - 5, 22 + i * 20))

            if status_timer > 0.0:
                hud_surf.blit(
                    font.render(status_msg, True, (120, 235, 150)),
                    (cw - panel_w - 5, 22 + len(info_lines) * 20 + 4),
                )

            slider_year.draw(hud_surf, font)
            slider_time.draw(hud_surf, font, data["time"].strftime("%Y-%m-%d %H:%M UTC"))
            slider_lat.draw(hud_surf, font)
            slider_lon.draw(hud_surf, font)
            slider_height.draw(hud_surf, font, height_str)
            gpu.upload_hud()

        gl.glDisable(gl.DEPTH_TEST)
        gl.glDisable(gl.CULL_FACE)
        gl.glEnable(gl.BLEND)
        gl.glBlendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
        gpu.draw_hud()

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
