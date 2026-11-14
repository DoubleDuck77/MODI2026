#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Symulator orbit wokół Księżyca: model grawitacyjny (w tym fizyka masconów) + wizualizacja 3D.

Wszystko (stan sondy, tekstura, siatka, mascony, punkty orientacyjne, tor podsatelitarny)
jest w JEDNYM układzie związanym z Księżycem (selenograficznym): x → (lat 0°, lon 0°),
y → (lat 0°, lon 90°E), z → biegun północny. Długość wschodnia dodatnia.

Dane rzeczywiste: coords/<rok>.csv (JPL Horizons, geocentryczne, ekliptyka J2000, w METRACH)
→ data UTC, kierunek Słońca (oświetlenie, terminator), punkt podziemski, perturbacje Ziemi i Słońca.

Wymagane: numpy, pygame, numba
Uruchomienie: python3 orbital.py [--epoch "YYYY-MM-DD HH:MM"]     (UTC; domyślnie teraz)
Teksturę umieść w ./Textures/moon_texture8K.jpg (lub obok skryptu).
"""

import argparse
import bisect
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pygame

try:
    from numba import njit
except ImportError:
    # Program nadal może działać bez Numba, choć wolniej.
    def njit(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda func: func


# ---------------------------- STAŁE FIZYCZNE ----------------------------

GM_MOON = 4902.800066       # km^3/s^2
R_MOON = 1737.4             # km
OMEGA_MOON = 2.6617e-6      # rad/s
GM_EARTH = 398600.4418      # km^3/s^2
GM_SUN = 1.32712440018e11   # km^3/s^2

# Niesferyczne harmoniczne pola grawitacyjnego Księżyca (LP150Q / GRAIL, nieznormalizowane)
J2 = 2.0329e-4              # spłaszczenie biegunowe (C20 = -J2)
C22 = 2.238e-5              # eliptyczność równikowa (wybrzuszenie pływowe w osi Ziemia-Księżyc)
J3 = -8.46e-6               # asymetria północ-południe (kluczowa dla frozen orbits)
J4 = 9.60e-6                # harmoniczna strefowa 4. stopnia

# Geofizyczny model masconów księżycowych (Plummer + ujemny pierścień kompensujący GRAIL).
# Każdy rekord: (nazwa, lat [deg], lon [deg], głębokość d [km], promień rdzenia b [km],
#                nadwyżka delta_mu = G*delta_M [km^3/s^2]).
# Parametry dobrane tak, aby odtwarzać obserwowane anomalie swobodnoruchowe (free-air)
# rzędu +150..+450 mGal na wysokości 50 km oraz ujemne otoczki wokół basenów.
LUNAR_MASCONS = [
    ("Mare Imbrium",         32.8,  -15.6, 30.0, 135.0, 0.145),
    ("Mare Serenitatis",     28.0,   17.5, 28.0, 115.0, 0.110),
    ("Mare Crisium",         17.0,   59.1, 25.0,  95.0, 0.082),
    ("Mare Nectaris",       -15.2,   34.6, 25.0,  90.0, 0.068),
    ("Mare Humorum",        -24.4,  -38.6, 25.0,  88.0, 0.064),
    ("Mare Smythii",         -1.8,   87.5, 26.0,  95.0, 0.066),
    ("Mare Orientale",      -19.4,  -92.8, 28.0, 110.0, 0.088),
    ("Mare Humboldtianum",   56.9,   81.5, 26.0,  90.0, 0.056),
    ("Mendel-Rydberg",      -50.0,  -94.0, 26.0,  85.0, 0.050),
    ("Mare Moscoviense",     27.3,  147.9, 25.0,  82.0, 0.054),
    ("Freundlich-Sharonov",  18.5,  175.0, 25.0,  80.0, 0.044),
    ("Hertzsprung",           1.5, -128.5, 26.0,  92.0, 0.048),
    ("Korolev",              -4.5, -157.4, 25.0,  85.0, 0.042),
    ("Schrödinger",         -75.0,  132.4, 24.0,  75.0, 0.038),
]

MASCON_COLLAR_FACTOR = 0.60   # ujemna otoczka izostatyczna wokół niecki (struktura bulls-eye GRAIL)
MASCON_COLLAR_SCALE = 2.10    # promień rozmycia otoczki względem rdzenia


def _build_mascon_arrays():
    n = len(LUNAR_MASCONS)
    xyz = np.zeros((n, 3), dtype=np.float64)
    mu = np.zeros(n, dtype=np.float64)
    b2_core = np.zeros(n, dtype=np.float64)
    b2_collar = np.zeros(n, dtype=np.float64)
    for i, (_, lat_deg, lon_deg, depth_km, b_km, dmu) in enumerate(LUNAR_MASCONS):
        lat = math.radians(lat_deg)
        lon = math.radians(lon_deg)
        rm = R_MOON - depth_km
        xyz[i, 0] = rm * math.cos(lat) * math.cos(lon)
        xyz[i, 1] = rm * math.cos(lat) * math.sin(lon)
        xyz[i, 2] = rm * math.sin(lat)
        mu[i] = dmu
        b2_core[i] = b_km * b_km
        bc = b_km * MASCON_COLLAR_SCALE
        b2_collar[i] = bc * bc
    # Kompensacja monopolu centralnego, aby całkowite GM Księżyca było ściśle zachowane
    net_excess = (1.0 - MASCON_COLLAR_FACTOR) * float(np.sum(mu))
    gm_compensated = GM_MOON - net_excess
    return xyz, mu, b2_core, b2_collar, gm_compensated


MASCON_XYZ, MASCON_MU, MASCON_B2_CORE, MASCON_B2_COLLAR, GM_MOON_COMPENSATED = _build_mascon_arrays()

R_ESCAPE = 120000.0          # km; granica obszaru symulacji
MAX_STEP = 2.0               # s; maksymalny krok RK4
SAMPLE_COS = math.cos(math.radians(0.5))   # nowa próbka toru po zmianie kierunku o 0.5°
SAMPLE_MAX_DT = 600.0        # s; albo najpóźniej co 10 min czasu symulacji


# Punkty orientacyjne na powierzchni Księżyca. Współrzędne: planetocentryczne,
# szerokość geograficzna i długość wschodnia w stopniach.
LUNAR_LANDMARKS = [
    ("Biegun N", 90.0, 0.0, "pole"),
    ("Biegun S", -90.0, 0.0, "pole"),
    ("Shackleton", -89.9, 0.0, "crater"),
    ("Apollo 11", 0.67416, 23.47314, "apollo"),
    ("Apollo 12", -3.0128, -23.4219, "apollo"),
    ("Apollo 14", -3.64589, -17.47194, "apollo"),
    ("Apollo 15", 26.13239, 3.63330, "apollo"),
    ("Apollo 16", -8.9734, 15.5011, "apollo"),
    ("Apollo 17", 20.1911, 30.7723, "apollo"),
    ("Luna 9", 7.13, -64.37, "ussr"),
    ("Luna 16", -0.5137, 56.3638, "ussr"),
    ("Lunokhod 1", 38.3150, -35.0081, "ussr"),
    ("Luna 17", 38.2376, -35.0016, "ussr"),
    ("Luna 20", 3.7863, 56.6242, "ussr"),
    ("Lunokhod 2", 25.8323, 30.9222, "ussr"),
    ("Luna 21", 25.9994, 30.4076, "ussr"),
    ("Luna 24", 12.7142, 62.2129, "ussr"),
    ("Chang'e 3", 44.1214, -19.5117, "china"),
    ("Chang'e 4", -45.4561, 177.5885, "china"),
    ("Chang'e 5", 43.0576, -51.9161, "china"),
    ("Chang'e 6", -41.6385, -153.9852, "china"),
    ("Chandrayaan-3", -69.3741, 32.3200, "india"),
    ("SLIM", -13.3160, 25.2510, "japan"),
]
LANDMARK_COLORS = {
    "pole": (255, 245, 150), "crater": (255, 100, 220),
    "apollo": (255, 190, 70), "ussr": (90, 220, 255),
    "china": (255, 100, 100), "india": (255, 145, 65),
    "japan": (190, 150, 255),
}


def latlon_to_xyz(lat_deg, lon_deg, radius=R_MOON):
    """Planetocentryczne (lat, lon) [deg] → wektor w układzie związanym z Księżycem (wektorowo)."""
    lat, lon = np.broadcast_arrays(np.radians(np.asarray(lat_deg, dtype=np.float64)),
                                   np.radians(np.asarray(lon_deg, dtype=np.float64)))
    cl = np.cos(lat)
    return np.stack([radius*cl*np.cos(lon), radius*cl*np.sin(lon), radius*np.sin(lat)], axis=-1)


def xyz_to_latlon(v):
    """Wektor(y) w układzie związanym z Księżycem → (lat, lon) [deg]."""
    v = np.asarray(v, dtype=np.float64)
    r = np.linalg.norm(v, axis=-1)
    lat = np.degrees(np.arcsin(np.clip(v[..., 2] / np.maximum(r, 1e-12), -1.0, 1.0)))
    lon = np.degrees(np.arctan2(v[..., 1], v[..., 0]))
    return lat, lon


# ------------------------------- GRAWITACJA -------------------------------

@njit
def mascon_accel(x, y, z):
    """Przyspieszenie od 14 basenów masconowych [km/s^2] (potencjał Plummera + pierścień GRAIL)."""
    ax, ay, az = 0.0, 0.0, 0.0
    n = MASCON_XYZ.shape[0]
    for i in range(n):
        dx = x - MASCON_XYZ[i, 0]
        dy = y - MASCON_XYZ[i, 1]
        dz = z - MASCON_XYZ[i, 2]
        d2 = dx*dx + dy*dy + dz*dz

        rc2 = d2 + MASCON_B2_CORE[i]
        inv_rc3 = 1.0 / (rc2 * math.sqrt(rc2))

        ro2 = d2 + MASCON_B2_COLLAR[i]
        inv_ro3 = 1.0 / (ro2 * math.sqrt(ro2))

        fac = -MASCON_MU[i] * (inv_rc3 - MASCON_COLLAR_FACTOR * inv_ro3)
        ax += fac * dx
        ay += fac * dy
        az += fac * dz
    return ax, ay, az


@njit
def moon_gravity_accel(x, y, z, use_mascons=True):
    """Przyspieszenie grawitacyjne w układzie związanym z Księżycem [km/s^2].

    Model bazowy: monopol + J2.
    Gdy use_mascons=True:
      * monopol skompensowany (GM_MOON_COMPENSATED), aby całkowite GM było zachowane,
      * harmoniczne C22 (wybrzuszenie pływowe), J3 i J4,
      * 14 fizycznych basenów masconowych (Plummer + pierścień izostatyczny GRAIL).
    """
    r2 = x*x + y*y + z*z
    r = math.sqrt(r2)
    if r < 1.0:
        return 0.0, 0.0, 0.0

    gm = GM_MOON_COMPENSATED if use_mascons else GM_MOON
    r3 = r2 * r
    gm_r3 = gm / r3
    mu_r3 = -gm_r3

    ax = mu_r3 * x
    ay = mu_r3 * y
    az = mu_r3 * z

    inv_r = 1.0 / r
    rr = R_MOON * inv_r
    rr2 = rr * rr
    u = z * inv_r
    u2 = u * u

    # Składnik strefowy J2 (spłaszczenie biegunowe)
    j2 = 1.5 * J2 * rr2
    ax += mu_r3 * j2 * x * (5.0 * u2 - 1.0)
    ay += mu_r3 * j2 * y * (5.0 * u2 - 1.0)
    az += mu_r3 * j2 * z * (5.0 * u2 - 3.0)

    if use_mascons:
        # Składnik sektoralny C22 (eliptyczność równikowa w osi Ziemia-Księżyc)
        c22 = 3.0 * C22 * rr2 * gm_r3
        dxy = (x*x - y*y) / r2
        ax += c22 * x * (2.0 - 5.0 * dxy)
        ay += c22 * y * (-2.0 - 5.0 * dxy)
        az += c22 * z * (-5.0 * dxy)

        # Składnik strefowy J3 (asymetria północ-południe)
        rr3 = rr2 * rr
        j3 = 2.5 * J3 * rr3 * gm_r3
        ax += j3 * x * u * (7.0 * u2 - 3.0)
        ay += j3 * y * u * (7.0 * u2 - 3.0)
        az += j3 * r * (7.0 * u2 * u2 - 6.0 * u2 + 0.6)

        # Składnik strefowy J4
        rr4 = rr2 * rr2
        u4 = u2 * u2
        j4 = 0.625 * J4 * rr4 * gm_r3
        ax += j4 * x * 3.0 * (21.0 * u4 - 14.0 * u2 + 1.0)
        ay += j4 * y * 3.0 * (21.0 * u4 - 14.0 * u2 + 1.0)
        az += j4 * z * (63.0 * u4 - 70.0 * u2 + 15.0)

        # Anomalie lokalne od 14 basenów masconowych
        mx, my, mz = mascon_accel(x, y, z)
        ax += mx
        ay += my
        az += mz

    return ax, ay, az


@njit
def third_body_accel(x, y, z, bx, by, bz, gm):
    """Perturbacja od trzeciego ciała w układzie środka Księżyca."""
    dx, dy, dz = bx - x, by - y, bz - z
    d2 = dx*dx + dy*dy + dz*dz
    d3 = d2 * math.sqrt(d2)
    b2 = bx*bx + by*by + bz*bz
    b3 = b2 * math.sqrt(b2)
    return gm*(dx/d3 - bx/b3), gm*(dy/d3 - by/b3), gm*(dz/d3 - bz/b3)


@njit
def derivatives(x, y, z, vx, vy, vz, use_mascons, third_body, earth, sun):
    ax, ay, az = moon_gravity_accel(x, y, z, use_mascons)
    if third_body:
        ex, ey, ez = third_body_accel(x, y, z, earth[0], earth[1], earth[2], GM_EARTH)
        sx, sy, sz = third_body_accel(x, y, z, sun[0], sun[1], sun[2], GM_SUN)
        ax += ex + sx
        ay += ey + sy
        az += ez + sz
    # Układ obracający się z Księżycem: a_cor = -2 omega x v; a_cent = -omega x (omega x r)
    w = OMEGA_MOON
    ax += w*w*x + 2.0*w*vy
    ay += w*w*y - 2.0*w*vx
    return vx, vy, vz, ax, ay, az


@njit
def rk4_step(x, y, z, vx, vy, vz, dt, use_mascons, third_body, earth, sun):
    k1 = derivatives(x, y, z, vx, vy, vz, use_mascons, third_body, earth, sun)
    k2 = derivatives(
        x + 0.5*dt*k1[0], y + 0.5*dt*k1[1], z + 0.5*dt*k1[2],
        vx + 0.5*dt*k1[3], vy + 0.5*dt*k1[4], vz + 0.5*dt*k1[5],
        use_mascons, third_body, earth, sun)
    k3 = derivatives(
        x + 0.5*dt*k2[0], y + 0.5*dt*k2[1], z + 0.5*dt*k2[2],
        vx + 0.5*dt*k2[3], vy + 0.5*dt*k2[4], vz + 0.5*dt*k2[5],
        use_mascons, third_body, earth, sun)
    k4 = derivatives(
        x + dt*k3[0], y + dt*k3[1], z + dt*k3[2],
        vx + dt*k3[3], vy + dt*k3[4], vz + dt*k3[5],
        use_mascons, third_body, earth, sun)

    return (
        x + dt*(k1[0] + 2*k2[0] + 2*k3[0] + k4[0])/6.0,
        y + dt*(k1[1] + 2*k2[1] + 2*k3[1] + k4[1])/6.0,
        z + dt*(k1[2] + 2*k2[2] + 2*k3[2] + k4[2])/6.0,
        vx + dt*(k1[3] + 2*k2[3] + 2*k3[3] + k4[3])/6.0,
        vy + dt*(k1[4] + 2*k2[4] + 2*k3[4] + k4[4])/6.0,
        vz + dt*(k1[5] + 2*k2[5] + 2*k3[5] + k4[5])/6.0,
    )


STATUS_OK, STATUS_CRASH, STATUS_ESCAPE, STATUS_NAN = 0, 1, 2, 3


@njit
def propagate(state, t, n_steps, step, use_mascons, third_body,
              earth0, earth1, sun0, sun1, last_sample, samples):
    """Całkuje n_steps kroków RK4; `state` (x, y, z, vx, vy, vz) jest aktualizowany w miejscu."""
    x, y, z = state[0], state[1], state[2]
    vx, vy, vz = state[3], state[4], state[5]
    earth = np.empty(3)
    sun = np.empty(3)
    total = n_steps * step
    n_samples = 0
    status = STATUS_OK
    for k in range(n_steps):
        w = (k * step) / total if total > 0.0 else 0.0
        for i in range(3):
            earth[i] = earth0[i] + w * (earth1[i] - earth0[i])
            sun[i] = sun0[i] + w * (sun1[i] - sun0[i])
        x, y, z, vx, vy, vz = rk4_step(x, y, z, vx, vy, vz, step,
                                       use_mascons, third_body, earth, sun)
        t += step
        r = math.sqrt(x*x + y*y + z*z)
        if not (math.isfinite(r) and math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz)):
            status = STATUS_NAN
            break
        lx, ly, lz = last_sample[0], last_sample[1], last_sample[2]
        lr = math.sqrt(lx*lx + ly*ly + lz*lz)
        cos_ang = (x*lx + y*ly + z*lz) / (r * lr) if lr > 0.0 else -1.0
        done = r <= R_MOON or r > R_ESCAPE
        if (done or cos_ang < SAMPLE_COS or abs(r - lr) > 0.01*lr
                or t - last_sample[3] >= SAMPLE_MAX_DT):
            if n_samples < samples.shape[0]:
                samples[n_samples, 0] = x
                samples[n_samples, 1] = y
                samples[n_samples, 2] = z
                samples[n_samples, 3] = t
                n_samples += 1
            last_sample[0], last_sample[1], last_sample[2], last_sample[3] = x, y, z, t
        if r <= R_MOON:
            status = STATUS_CRASH
            break
        if r > R_ESCAPE:
            status = STATUS_ESCAPE
            break
    state[0], state[1], state[2] = x, y, z
    state[3], state[4], state[5] = vx, vy, vz
    return status, t, n_samples


def mascon_diagnostics(pos):
    """Zwraca (dg_radial_mgal, dg_horiz_mgal, nazwa_najbliższego_basenu_lub_None)."""
    x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
    r = math.sqrt(x*x + y*y + z*z)
    if r < 1.0:
        return 0.0, 0.0, None
    ax, ay, az = mascon_accel(x, y, z)
    a_vec = np.array([ax, ay, az])
    r_hat = np.array([x, y, z]) / r
    # Dodatnie dg_radial oznacza silniejsze przyciąganie w dół (nadwyżka masy)
    a_rad = float(a_vec @ r_hat)
    dg_radial_mgal = -a_rad * 1e8
    a_horiz = float(np.linalg.norm(a_vec - a_rad * r_hat))
    dg_horiz_mgal = a_horiz * 1e8

    # Najbliższy basen (odległość kątowa na sferze)
    surf_pt = r_hat * R_MOON
    dists = np.linalg.norm(MASCON_XYZ - surf_pt, axis=1)
    idx = int(np.argmin(dists))
    nearest = LUNAR_MASCONS[idx][0] if dists[idx] < 450.0 else None
    return dg_radial_mgal, dg_horiz_mgal, nearest


def orbital_state(altitude_km, inclination_deg, speed_kms, true_anomaly_deg=0.0,
                  latitude_deg=0.0, longitude_deg=0.0):
    """Stan w układzie obracającym się z Księżycem."""
    r = R_MOON + altitude_km
    inc = math.radians(inclination_deg)
    lat, lon = math.radians(latitude_deg), math.radians(longitude_deg)
    radial = np.array([math.cos(lat)*math.cos(lon),
                       math.cos(lat)*math.sin(lon), math.sin(lat)])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat)*math.cos(lon),
                      -math.sin(lat)*math.sin(lon), math.cos(lat)])
    pos = r * radial
    tangent = math.cos(inc)*east + math.sin(inc)*north
    v_inertial = speed_kms * tangent
    omega_cross_r = np.array([-OMEGA_MOON*pos[1], OMEGA_MOON*pos[0], 0.0])
    return pos, v_inertial - omega_cross_r


def inertial_velocity(pos, vel_rot):
    """Prędkość względem środka Księżyca w układzie nieobracającym się: v + ω × r."""
    return np.array([vel_rot[0] - OMEGA_MOON*pos[1], vel_rot[1] + OMEGA_MOON*pos[0], vel_rot[2]])


def osculating_elements(pos, vel_rot):
    """Elementy oskulacyjne (2 ciała): (hp_km, ha_km, ecc, inc_deg)."""
    r = float(np.linalg.norm(pos))
    v = inertial_velocity(pos, vel_rot)
    v2 = float(v @ v)
    energy = 0.5 * v2 - GM_MOON / r
    h_vec = np.cross(pos, v)
    h = float(np.linalg.norm(h_vec))
    inc_deg = math.degrees(math.acos(max(-1.0, min(1.0, h_vec[2] / max(h, 1e-12)))))
    if energy >= 0.0:
        return r - R_MOON, float("inf"), 1.0, inc_deg
    a = -GM_MOON / (2.0 * energy)
    ecc = math.sqrt(max(0.0, 1.0 - h*h / (GM_MOON * a)))
    hp = a * (1.0 - ecc) - R_MOON
    ha = a * (1.0 + ecc) - R_MOON
    return hp, ha, ecc, inc_deg


def orbit_extent(pos, vel_rot):
    """Największa odległość od środka Księżyca na orbicie oskulacyjnej (2 ciała), co najmniej |r|."""
    r = float(np.linalg.norm(pos))
    _, ha, ecc, _ = osculating_elements(pos, vel_rot)
    if ecc >= 1.0 or not math.isfinite(ha):
        return R_ESCAPE
    return min(R_ESCAPE, max(r, R_MOON + ha))


def circular_speed(altitude_km):
    return math.sqrt(GM_MOON / (R_MOON + altitude_km))


# --------------------------- EFEMERYDY I ORIENTACJA ---------------------------

EPHEM_START = datetime(2000, 1, 1)
EPHEM_END = datetime(2100, 1, 1)
J2000_OFFSET_S = 12 * 3600.0
I_MOON_EQ = math.radians(1.5424)


def to_ephem_seconds(dt):
    return (dt - EPHEM_START).total_seconds()


def from_ephem_seconds(seconds):
    return EPHEM_START + timedelta(seconds=seconds)


class Ephemeris:
    """Położenia Słońca i Księżyca z coords/<rok>.csv (JPL Horizons, 500@399, ekliptyka J2000)."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self._years = {}
        self._year_start_h = [(datetime(y, 1, 1) - EPHEM_START) // timedelta(hours=1)
                              for y in range(2000, 2102)]
        self.t_min = 0.0
        self.t_max = to_ephem_seconds(EPHEM_END)

    @staticmethod
    def locate():
        candidates = []
        env_path = os.environ.get("MOON_COORDS")
        if env_path:
            candidates.append(Path(env_path).expanduser())
        candidates += [Path(__file__).resolve().parent / "coords", Path.cwd() / "coords"]
        for folder in candidates:
            if (folder / "2000.csv").is_file():
                return folder
        return None

    def _rows(self, year):
        rows = self._years.get(year)
        if rows is None:
            path = self.folder / f"{year}.csv"
            rows = np.loadtxt(path, delimiter=",", skiprows=1, usecols=range(1, 7), ndmin=2) / 1000.0
            self._years[year] = rows
        return rows

    def _row(self, hour):
        year = 2000 + bisect.bisect_right(self._year_start_h, hour) - 1
        return self._rows(year)[hour - self._year_start_h[year - 2000]]

    def state(self, t):
        t = min(max(t, self.t_min), self.t_max)
        h = t / 3600.0
        i = min(int(math.floor(h)), int(self.t_max // 3600) - 1)
        f = h - i
        r0 = self._row(i)
        r1 = self._row(i + 1)
        r = r0 + f * (r1 - r0)
        return r[0:3], r[3:6]

    def moon_velocity(self, t, h=3600.0):
        t0 = max(self.t_min, t - h)
        t1 = min(self.t_max, t + h)
        return (self.state(t1)[1] - self.state(t0)[1]) / (t1 - t0)


def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def lunar_body_matrix(d_j2000):
    omega = math.radians(125.04452 - 0.0529537648 * d_j2000)
    L = math.radians(218.3164477 + 13.17639648 * d_j2000)
    node_eq = omega + math.pi
    W = L - node_eq + math.pi
    return _rot_z(-W) @ _rot_x(-I_MOON_EQ) @ _rot_z(-node_eq)


def moon_frame_vectors(eph, t):
    sun, moon = eph.state(t)
    m = lunar_body_matrix((t - J2000_OFFSET_S) / 86400.0)
    return m @ (-moon), m @ (sun - moon)


NRHO_9_2 = (1.022028214026, 0.0, -0.182101394053, 0.0, -0.103270947609, 0.0)


def nrho_state(eph, t):
    mu = GM_MOON / (GM_EARTH + GM_MOON)
    _, moon = eph.state(t)
    v_moon = eph.moon_velocity(t)
    L = float(np.linalg.norm(moon))
    L_dot = float(moon @ v_moon) / L
    h = np.cross(moon, v_moon)
    x_hat = moon / L
    z_hat = h / np.linalg.norm(h)
    y_hat = np.cross(z_hat, x_hat)
    axes = np.column_stack([x_hat, y_hat, z_hat])
    omega = h / (L * L)
    t_star = math.sqrt(L**3 / (GM_EARTH + GM_MOON))

    rho = np.array(NRHO_9_2[:3]) - np.array([1.0 - mu, 0.0, 0.0])
    rho_dot = np.array(NRHO_9_2[3:])
    r_ecl = L * (axes @ rho)
    v_ecl = L_dot * (axes @ rho) + np.cross(omega, r_ecl) + (L / t_star) * (axes @ rho_dot)

    m = lunar_body_matrix((t - J2000_OFFSET_S) / 86400.0)
    r_body = m @ r_ecl
    v_body = m @ v_ecl
    v_rot = v_body - np.array([-OMEGA_MOON * r_body[1], OMEGA_MOON * r_body[0], 0.0])
    return r_body, v_rot


def get_preset_orbit(name, eph=None, t=0.0):
    if name == "LRO":
        # LRO: około kołowa orbita polarna, 50 km; podlega silnym zaburzeniom masconowym.
        return orbital_state(50.0, 90.0, circular_speed(50.0))
    if name == "Gateway":
        if eph is not None:
            return nrho_state(eph, t)
        rp, ra = R_MOON + 3000.0, R_MOON + 70000.0
        a = 0.5*(rp+ra)
        vp = math.sqrt(GM_MOON*(2.0/rp - 1.0/a))
        return orbital_state(3000.0, 90.0, vp)
    if name == "Luna 10":
        rp, ra = R_MOON + 350.0, R_MOON + 1016.0
        a = 0.5*(rp+ra)
        vp = math.sqrt(GM_MOON*(2.0/rp - 1.0/a))
        return orbital_state(350.0, 71.9, vp)
    if name == "Apollo PFS-2":
        # Subsatelita Apollo 16 (PFS-2): niska orbita okołorównikowa (~96 x 118 km, i=11.2°),
        # przecinająca pas masconów bliskiej strony; mimośród rośnie aż do uderzenia w powierzchnię.
        rp, ra = R_MOON + 96.0, R_MOON + 118.0
        a = 0.5 * (rp + ra)
        vp = math.sqrt(GM_MOON * (2.0 / rp - 1.0 / a))
        return orbital_state(96.0, 11.2, vp, latitude_deg=0.0, longitude_deg=-20.0)
    return orbital_state(100.0, 45.0, circular_speed(100.0))


# -------------------------------- KAMERA --------------------------------

class OrbitCamera:
    """Kamera perspektywiczna krążąca wokół środka Księżyca."""

    MIN_DIST = R_MOON * 1.35
    MAX_DIST = 300000.0

    def __init__(self, lat_deg=15.0, lon_deg=0.0, dist=6000.0):
        self.dist = dist
        self.set_view(lat_deg, lon_deg)

    def set_view(self, lat_deg, lon_deg):
        self.lat = max(-89.5, min(89.5, float(lat_deg)))
        self.lon = (float(lon_deg) + 180.0) % 360.0 - 180.0
        lat, lon = math.radians(self.lat), math.radians(self.lon)
        self.c = np.array([math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)])
        fwd = -self.c
        right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
        self.right = right / np.linalg.norm(right)
        self.up = np.cross(self.right, fwd)

    def zoom(self, factor):
        self.dist = max(self.MIN_DIST, min(self.MAX_DIST, self.dist * factor))

    @property
    def position(self):
        return self.dist * self.c

    def project(self, pts, cx, cy, focal):
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        depth = self.dist - pts @ self.c
        safe = np.where(depth > 1.0, depth, 1.0)
        sx = cx + (pts @ self.right) * focal / safe
        sy = cy - (pts @ self.up) * focal / safe
        return sx, sy, depth

    def visible(self, pts):
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        cam = self.position
        v = pts - cam
        vv = np.einsum("ij,ij->i", v, v)
        s = -(v @ cam) / np.maximum(vv, 1e-12)
        closest = cam + s[:, None] * v
        hidden = (s > 0.0) & (s < 1.0) & (np.einsum("ij,ij->i", closest, closest) < R_MOON*R_MOON*(1.0 - 1e-9))
        return (self.dist - pts @ self.c > 1.0) & ~hidden

    def apparent_radius(self, focal):
        D = self.dist
        return focal * R_MOON / math.sqrt(D*D - R_MOON*R_MOON)


def draw_runs(screen, color, xs, ys, ok, cut=None, width=1):
    xs = np.asarray(xs)
    ys = np.asarray(ys)
    ok = np.asarray(ok) & (np.abs(xs) < 1e5) & (np.abs(ys) < 1e5)
    if xs.size < 2:
        return
    link = ok[:-1] & ok[1:]
    if cut is not None:
        link &= ~np.asarray(cut)
    idx = np.flatnonzero(link)
    if idx.size == 0:
        return
    breaks = np.flatnonzero(np.diff(idx) != 1)
    starts = np.concatenate([[idx[0]], idx[breaks + 1]])
    ends = np.concatenate([idx[breaks], [idx[-1]]])
    for s, e in zip(starts, ends):
        pts = np.column_stack([xs[s:e+2], ys[s:e+2]]).tolist()
        if width > 1:
            pygame.draw.lines(screen, color, False, pts, width)
        else:
            pygame.draw.aalines(screen, color, False, pts)


# ------------------------------- TEKSTURA -------------------------------

def find_texture():
    script_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    candidates = [
        script_dir / "Textures" / "moon_texture8K.jpg",
        script_dir / "textures" / "moon_texture8K.jpg",
        script_dir / "moon_texture8K.jpg",
        cwd / "Textures" / "moon_texture8K.jpg",
        cwd / "textures" / "moon_texture8K.jpg",
        cwd / "moon_texture8K.jpg",
    ]
    env_path = os.environ.get("MOON_TEXTURE")
    if env_path:
        candidates.insert(0, Path(env_path).expanduser())

    for path in candidates:
        if path.is_file():
            return path
    return None


def load_texture():
    path = find_texture()
    if path is None:
        print("[WARN] Nie znaleziono tekstury Księżyca.")
        print("       Oczekiwana lokalizacja: Textures/moon_texture8K.jpg")
        print("       Możesz też ustawić zmienną MOON_TEXTURE.")
        return None

    try:
        print(f"[INFO] Wczytywanie tekstury: {path}")
        image = pygame.image.load(str(path))
        image = image.convert()
        max_width = 4096
        if image.get_width() > max_width:
            h = max(1, round(image.get_height() * max_width / image.get_width()))
            image = pygame.transform.smoothscale(image, (max_width, h))
        levels = []
        while True:
            levels.append(pygame.surfarray.array3d(image))
            if image.get_width() <= 512:
                break
            image = pygame.transform.smoothscale(
                image, (image.get_width() // 2, max(1, image.get_height() // 2)))
        print(f"[OK] Tekstura załadowana: {levels[0].shape[0]} x {levels[0].shape[1]} "
              f"(+{len(levels) - 1} poziomy mipmap)")
        return levels
    except (pygame.error, OSError) as exc:
        print(f"[ERROR] Nie udało się wczytać tekstury: {exc}")
        return None


def pick_texture_level(levels, camera, focal):
    need = 2.0 * math.pi * R_MOON * focal / max(camera.dist - R_MOON, 1e-6)
    for level in reversed(levels):
        if level.shape[0] >= need:
            return level
    return levels[0]


FALLBACK_LIGHT = np.array([0.35, -0.25, 0.90]) / np.linalg.norm([0.35, -0.25, 0.90])
AMBIENT = 0.005
GAMMA = 2.2


def render_textured_moon(screen, camera, center, focal, levels, sun_dir=None, clip_rect=None):
    cx, cy = center
    D = camera.dist
    if D <= R_MOON or focal <= 0:
        return

    radius = camera.apparent_radius(focal)
    if radius < 2:
        pygame.draw.circle(screen, (145, 145, 150), (int(cx), int(cy)), max(1, int(radius)))
        return
    if levels is None:
        pygame.draw.circle(screen, (125, 125, 130), (int(cx), int(cy)), int(radius))
        pygame.draw.circle(screen, (185, 185, 190), (int(cx), int(cy)), int(radius), 1)
        return

    clip = (clip_rect or screen.get_rect()).clip(screen.get_rect())
    r_int = int(math.ceil(radius)) + 1
    box = pygame.Rect(int(cx) - r_int, int(cy) - r_int, 2*r_int + 1, 2*r_int + 1).clip(clip)
    if box.width <= 0 or box.height <= 0:
        return

    qx = ((np.arange(box.x, box.right, dtype=np.float64) - cx) / focal)[:, None]
    qy = (-(np.arange(box.y, box.bottom, dtype=np.float64) - cy) / focal)[None, :]
    qa = 1.0 + qx*qx + qy*qy
    discriminant = D*D - qa*(D*D - R_MOON*R_MOON)
    mask = discriminant >= 0.0
    if not mask.any():
        return
    qa_m = qa[mask]
    qx_m = np.broadcast_to(qx, mask.shape)[mask]
    qy_m = np.broadcast_to(qy, mask.shape)[mask]
    t = (D - np.sqrt(discriminant[mask])) / qa_m

    c, right, up = camera.c, camera.right, camera.up
    a, b, d = D - t, t*qx_m, t*qy_m
    nx = (a*c[0] + b*right[0] + d*up[0]) / R_MOON
    ny = (a*c[1] + b*right[1] + d*up[1]) / R_MOON
    nz = (a*c[2] + b*right[2] + d*up[2]) / R_MOON

    lat = np.arcsin(np.clip(nz, -1.0, 1.0))
    lon = np.arctan2(ny, nx)

    texture = pick_texture_level(levels, camera, focal)
    tex_w, tex_h = texture.shape[0], texture.shape[1]
    ui = ((lon + math.pi) / (2.0*math.pi) * tex_w).astype(np.int32) % tex_w
    vi = np.clip(((math.pi/2.0 - lat) / math.pi * tex_h).astype(np.int32), 0, tex_h - 1)
    sampled = texture[ui, vi].astype(np.float32)

    s = FALLBACK_LIGHT if sun_dir is None else sun_dir
    mu0 = nx*s[0] + ny*s[1] + nz*s[2]
    mu = (D*(nx*c[0] + ny*c[1] + nz*c[2]) - R_MOON) / (t*np.sqrt(qa_m))
    lit = np.where(mu0 > 0.0, np.minimum(1.0, 2.0*mu0 / np.maximum(mu0 + mu, 1e-6)), 0.0)
    illumination = (AMBIENT + (1.0 - AMBIENT) * lit) ** (1.0 / GAMMA)
    sampled = np.clip(sampled * illumination[:, None], 0, 255).astype(np.uint8)

    try:
        pixels = pygame.surfarray.pixels3d(screen.subsurface(box))
        pixels[mask] = sampled
        del pixels
    except (ValueError, pygame.error):
        buf = np.zeros((box.width, box.height, 3), dtype=np.uint8)
        buf[mask] = np.maximum(sampled, 1)
        tmp = pygame.surfarray.make_surface(buf)
        tmp.set_colorkey((0, 0, 0))
        screen.blit(tmp, box.topleft)
    pygame.draw.circle(screen, (175, 180, 190), (int(cx), int(cy)), int(radius), 1)


_GRID_LINES = None
_LANDMARK_XYZ = latlon_to_xyz([lm[1] for lm in LUNAR_LANDMARKS],
                              [lm[2] for lm in LUNAR_LANDMARKS], R_MOON * 1.012)


def _build_mascon_rings():
    """Okręgi na powierzchni Księżyca odpowiadające promieniom rdzeni masconów."""
    rings = []
    alphas = np.linspace(0.0, 2.0 * math.pi, 49)
    for name, lat_deg, lon_deg, _, b_km, _ in LUNAR_MASCONS:
        center_u = latlon_to_xyz(lat_deg, lon_deg, 1.0)
        # Baza styczna w punkcie (lat, lon)
        ref = np.array([0.0, 0.0, 1.0]) if abs(center_u[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        e1 = np.cross(ref, center_u)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(center_u, e1)
        psi = b_km / R_MOON  # promień kątowy rdzenia [rad]
        pts = (math.cos(psi) * center_u[None, :]
               + math.sin(psi) * (np.cos(alphas)[:, None] * e1[None, :]
                                  + np.sin(alphas)[:, None] * e2[None, :])) * (R_MOON * 1.006)
        rings.append((name, center_u * (R_MOON * 1.012), pts))
    return rings


_MASCON_RINGS = _build_mascon_rings()


def grid_lines():
    global _GRID_LINES
    if _GRID_LINES is None:
        lines = []
        lons = np.arange(-180, 181, 3, dtype=np.float64)
        lats = np.arange(-90, 91, 3, dtype=np.float64)
        for lat in range(-75, 76, 15):
            lines.append(latlon_to_xyz(np.full_like(lons, lat), lons, R_MOON * 1.004))
        for lon in range(-180, 180, 15):
            lines.append(latlon_to_xyz(lats, np.full_like(lats, lon), R_MOON * 1.004))
        _GRID_LINES = lines
    return _GRID_LINES


def draw_mascon_overlays_3d(screen, camera, center, focal, font_small, label_rect):
    """Rysuje obrysy rdzeni masconów i ich etykiety na globie 3D."""
    cx, cy = center
    radius = camera.apparent_radius(focal)
    if radius < 35:
        return
    ring_color = (255, 110, 145)
    for name, c_pt, ring_pts in _MASCON_RINGS:
        sx, sy, _ = camera.project(ring_pts, cx, cy, focal)
        draw_runs(screen, ring_color, sx, sy, camera.visible(ring_pts), width=1)
        if radius >= 110 and camera.visible(c_pt)[0]:
            csx, csy, _ = camera.project(c_pt, cx, cy, focal)
            x, y = int(csx[0]), int(csy[0])
            pygame.draw.circle(screen, ring_color, (x, y), 2)
            label = font_small.render(name, True, (255, 150, 175))
            lx, ly = x + 6, y - label.get_height() // 2
            if label_rect.contains(pygame.Rect(lx, ly, label.get_width() + 1, label.get_height() + 1)):
                shadow = font_small.render(name, True, (5, 8, 12))
                screen.blit(shadow, (lx + 1, ly + 1))
                screen.blit(label, (lx, ly))


def draw_lunar_grid_and_landmarks(screen, camera, center, focal, font_small, label_rect):
    cx, cy = center
    radius = camera.apparent_radius(focal)
    if radius < 25:
        return
    grid_color = (95, 155, 175)
    for line in grid_lines():
        sx, sy, _ = camera.project(line, cx, cy, focal)
        draw_runs(screen, grid_color, sx, sy, camera.visible(line))

    sx, sy, _ = camera.project(_LANDMARK_XYZ, cx, cy, focal)
    vis = camera.visible(_LANDMARK_XYZ)
    for i, (name, _, _, category) in enumerate(LUNAR_LANDMARKS):
        if not vis[i]:
            continue
        x, y = int(sx[i]), int(sy[i])
        color = LANDMARK_COLORS.get(category, (255, 255, 255))
        pygame.draw.circle(screen, (8, 12, 18), (x, y), 5)
        pygame.draw.circle(screen, color, (x, y), 3)
        if radius < 120:
            continue
        label = font_small.render(name, True, color)
        lx, ly = x + 7, y - label.get_height() // 2
        if label_rect.contains(pygame.Rect(lx, ly, label.get_width() + 1, label.get_height() + 1)):
            shadow = font_small.render(name, True, (5, 8, 12))
            screen.blit(shadow, (lx+1, ly+1))
            screen.blit(label, (lx, ly))


def draw_sun_marker(screen, x, y, size=6):
    for k in range(8):
        a = k * math.pi / 4
        pygame.draw.line(screen, (255, 210, 60),
                         (x + math.cos(a)*(size+2), y + math.sin(a)*(size+2)),
                         (x + math.cos(a)*(size+5), y + math.sin(a)*(size+5)))
    pygame.draw.circle(screen, (20, 16, 4), (x, y), size + 1)
    pygame.draw.circle(screen, (255, 220, 70), (x, y), size)


def draw_earth_marker(screen, x, y, size=6):
    pygame.draw.circle(screen, (8, 12, 18), (x, y), size + 2)
    pygame.draw.circle(screen, (70, 140, 255), (x, y), size)
    pygame.draw.circle(screen, (200, 230, 255), (x, y), size, 1)


# ------------------------------ TOR PODSATELITARNY ------------------------------

class TrackBuffer:
    def __init__(self, capacity=20000):
        self.data = np.zeros((capacity, 4), dtype=np.float64)
        self.count = 0
        self.head = 0

    def clear(self):
        self.count = 0
        self.head = 0

    def extend(self, rows):
        rows = np.asarray(rows, dtype=np.float64).reshape(-1, 4)
        cap = self.data.shape[0]
        if rows.shape[0] >= cap:
            rows = rows[-cap:]
        k = rows.shape[0]
        end = self.head + k
        if end <= cap:
            self.data[self.head:end] = rows
        else:
            first = cap - self.head
            self.data[self.head:] = rows[:first]
            self.data[:k - first] = rows[first:]
        self.head = end % cap
        self.count = min(cap, self.count + k)

    def view(self):
        if self.count < self.data.shape[0]:
            return self.data[:self.count]
        return np.concatenate([self.data[self.head:], self.data[:self.head]])


def antimeridian_cuts(lon_deg):
    return np.abs(np.diff(lon_deg)) > 180.0


class GroundTrackMap:
    def __init__(self, levels):
        self.levels = levels
        self._size = None
        self._base = None
        self._normals = None
        self._sun = None
        self._surface = None

    def _ensure(self, w, h):
        if self._size == (w, h):
            return
        self._size = (w, h)
        if self.levels is not None:
            src = next((lvl for lvl in reversed(self.levels) if lvl.shape[0] >= w), self.levels[0])
            surf = pygame.transform.smoothscale(pygame.surfarray.make_surface(src), (w, h))
            self._base = pygame.surfarray.array3d(surf).astype(np.float32)
        else:
            self._base = np.full((w, h, 3), 95.0, dtype=np.float32)
        lon = (np.arange(w) + 0.5) / w * 360.0 - 180.0
        lat = 90.0 - (np.arange(h) + 0.5) / h * 180.0
        self._normals = latlon_to_xyz(lat[None, :], lon[:, None], 1.0)
        self._sun = None
        self._surface = None

    def surface(self, w, h, sun_dir):
        self._ensure(w, h)
        if self._surface is not None:
            if sun_dir is None and self._sun is None:
                return self._surface
            if (sun_dir is not None and self._sun is not None
                    and float(sun_dir @ self._sun) > math.cos(math.radians(0.25))):
                return self._surface
        if sun_dir is None:
            img = self._base
        else:
            day = np.clip(self._normals @ sun_dir * 8.0 + 0.5, 0.0, 1.0)
            img = self._base * (0.35 + 0.65 * day)[..., None]
        self._surface = pygame.surfarray.make_surface(np.clip(img, 0, 255).astype(np.uint8))
        self._sun = None if sun_dir is None else np.array(sun_dir)
        return self._surface

    @staticmethod
    def to_xy(rect, lat, lon):
        x = rect.x + (np.asarray(lon) + 180.0) / 360.0 * rect.width
        y = rect.y + (90.0 - np.asarray(lat)) / 180.0 * rect.height
        return x, y

    def draw(self, screen, rect, track, t_now, recent_window, pos, sun_dir,
             subsolar, subearth, font, show_mascons=True):
        screen.blit(self.surface(rect.width, rect.height, sun_dir), rect.topleft)
        prev_clip = screen.get_clip()
        screen.set_clip(rect)
        grid = (70, 105, 125)
        for lon in range(-150, 180, 30):
            x = rect.x + (lon + 180) / 360.0 * rect.width
            pygame.draw.line(screen, grid, (x, rect.y), (x, rect.bottom))
        for lat in range(-60, 90, 30):
            y = rect.y + (90 - lat) / 180.0 * rect.height
            pygame.draw.line(screen, grid, (rect.x, y), (rect.right, y))

        if show_mascons:
            for _, lat_deg, lon_deg, _, b_km, _ in LUNAR_MASCONS:
                mx, my = self.to_xy(rect, lat_deg, lon_deg)
                rx = max(3, int(math.degrees(b_km / R_MOON) / 360.0 * rect.width))
                pygame.draw.circle(screen, (255, 110, 145), (int(mx), int(my)), rx, 1)

        lx, ly = self.to_xy(rect, [lm[1] for lm in LUNAR_LANDMARKS], [lm[2] for lm in LUNAR_LANDMARKS])
        for i, lm in enumerate(LUNAR_LANDMARKS):
            pygame.draw.circle(screen, LANDMARK_COLORS.get(lm[3], (255, 255, 255)),
                               (int(lx[i]), int(ly[i])), 2)

        if track.shape[0] >= 2:
            lat, lon = xyz_to_latlon(track[:, :3])
            x, y = self.to_xy(rect, lat, lon)
            cuts = antimeridian_cuts(lon)
            everything = np.ones(lat.shape, dtype=bool)
            draw_runs(screen, (150, 110, 60), x, y, everything, cuts)
            recent = track[:, 3] >= t_now - recent_window
            draw_runs(screen, (255, 170, 60), x, y, recent, cuts, width=2)

        for point, marker in ((subsolar, draw_sun_marker), (subearth, draw_earth_marker)):
            if point is not None:
                px, py = self.to_xy(rect, point[0], point[1])
                marker(screen, int(px), int(py), 5)

        lat, lon = xyz_to_latlon(pos)
        px, py = self.to_xy(rect, lat, lon)
        pygame.draw.circle(screen, (10, 10, 10), (int(px), int(py)), 6)
        pygame.draw.circle(screen, (255, 230, 90), (int(px), int(py)), 5)
        pygame.draw.circle(screen, (255, 80, 60), (int(px), int(py)), 2)
        screen.set_clip(prev_clip)

        pygame.draw.rect(screen, (45, 60, 80), rect, 1)
        for lon in (-180, -90, 0, 90, 180):
            txt = font.render(f"{lon:+d}" if lon else "0", True, (125, 140, 160))
            x = rect.x + (lon + 180) / 360.0 * rect.width - txt.get_width() / 2
            x = min(max(x, rect.x), rect.right - txt.get_width())
            screen.blit(txt, (x, rect.bottom + 2))


# ------------------------------- INTERFEJS -------------------------------

class TimeSlider:
    def __init__(self, x, y, w, h, min_val, max_val, val, label):
        self.rect = pygame.Rect(x, y, w, h)
        self.min_val = min_val
        self.max_val = max_val
        self.val = val
        self.label = label
        self.dragging = False

    def update_val(self, mouse_x):
        ratio = max(0.0, min(1.0, (mouse_x - self.rect.x) / max(1, self.rect.width)))
        self.val = self.min_val * (self.max_val / self.min_val) ** ratio

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.inflate(12, 14).collidepoint(event.pos):
                self.dragging = True
                self.update_val(event.pos[0])
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.update_val(event.pos[0])
            return True
        return False

    def draw(self, screen, font):
        pygame.draw.rect(screen, (50, 60, 75), self.rect, border_radius=4)
        ratio = math.log(self.val/self.min_val) / math.log(self.max_val/self.min_val)
        ratio = max(0.0, min(1.0, ratio))
        fill_w = int(self.rect.width * ratio)
        pygame.draw.rect(screen, (80, 150, 220),
                         (self.rect.x, self.rect.y, fill_w, self.rect.height), border_radius=4)
        pygame.draw.circle(screen, (240, 245, 255),
                           (self.rect.x + fill_w, self.rect.centery), 7)
        label = font.render(f"{self.label}: {self.val:,.1f}x", True, (220, 225, 235))
        screen.blit(label, (self.rect.x, self.rect.y - 22))


def parse_epoch(text):
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1]
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"niepoprawna data: {text!r} (oczekiwano YYYY-MM-DD HH:MM)") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Symulator orbit wokół Księżyca z fizyką masconów.")
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    parser.add_argument("--epoch", type=parse_epoch, default=now,
                        help="data startu symulacji w UTC, np. \"2026-11-14 12:00\" (domyślnie teraz)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    pygame.init()
    pygame.display.set_caption("Lunar Orbiter Simulator — fizyka masconów i teksturowany Księżyc")
    screen = pygame.display.set_mode((1400, 900), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("DejaVu Sans Mono", 14)
    font_small = pygame.font.SysFont("DejaVu Sans Mono", 12)
    font_bold = pygame.font.SysFont("DejaVu Sans Mono", 15, bold=True)

    texture = load_texture()
    track_map = GroundTrackMap(texture)

    eph_folder = Ephemeris.locate()
    eph = Ephemeris(eph_folder) if eph_folder is not None else None
    epoch = args.epoch
    if eph is None:
        print("[WARN] Nie znaleziono efemeryd coords/<rok>.csv — stałe oświetlenie, bez Ziemi i Słońca.")
    else:
        if not (EPHEM_START <= epoch < EPHEM_END):
            print(f"[ERROR] Epoka {epoch} poza zakresem efemeryd 2000-01-01 … 2100-01-01.")
            pygame.quit()
            sys.exit(2)
        print(f"[OK] Efemerydy: {eph_folder}  |  epoka: {epoch:%Y-%m-%d %H:%M:%S} UTC")
    epoch_s = to_ephem_seconds(epoch)

    presets = [
        ("LRO", "LRO"),
        ("Gateway NRHO", "Gateway"),
        ("Luna 10", "Luna 10"),
        ("Apollo PFS-2", "Apollo PFS-2"),
        ("Custom", "CUSTOM"),
    ]

    current_preset = "LRO"
    state = np.zeros(6, dtype=np.float64)
    last_sample = np.zeros(4, dtype=np.float64)
    track = TrackBuffer(20000)
    custom_dialog = False
    custom_fields = ["100", "45", f"{circular_speed(100.0):.4f}"]
    custom_active = 0
    custom_error = ""
    history_alt, history_vel = [], []
    max_history = 240
    time_elapsed = 0.0
    crashed = False
    crash_reason = ""
    paused = False
    perturbations = True
    use_mascons = True
    show_mascons = True
    show_ground_track = True
    fit_pending = True

    camera = OrbitCamera(lat_deg=15.0, lon_deg=0.0, dist=6000.0)
    dragging_cam = False
    last_mouse = (0, 0)
    slider = TimeSlider(30, 845, 300, 10, 1.0, 100000.0, 30.0, "Tempo symulacji")
    zero3 = np.zeros(3)

    def body_vectors(t_elapsed):
        if eph is None:
            return None, None
        return moon_frame_vectors(eph, epoch_s + t_elapsed)

    def set_state(pos, vel):
        nonlocal time_elapsed, crashed, crash_reason, fit_pending
        fit_pending = True
        state[:3] = pos
        state[3:] = vel
        track.clear()
        track.extend([[pos[0], pos[1], pos[2], 0.0]])
        last_sample[:] = (pos[0], pos[1], pos[2], 0.0)
        history_alt.clear()
        history_vel.clear()
        time_elapsed = 0.0
        crashed = False
        crash_reason = ""

    def reset_sim(preset=None):
        nonlocal current_preset
        if preset and preset != "RESET":
            current_preset = preset
        set_state(*get_preset_orbit(current_preset, eph, epoch_s))

    def apply_custom(alt, inc, speed):
        nonlocal current_preset, custom_dialog
        current_preset = "Custom"
        set_state(*orbital_state(alt, inc, speed))
        custom_dialog = False

    reset_sim()

    running = True
    while running:
        dt_real = min(clock.tick(60) / 1000.0, 0.05)
        width, height = screen.get_size()
        slider.rect.y = height - 48
        panel_x = max(650, int(width*0.55))
        panel_w = max(250, width - panel_x - 25)
        panel_top = 75
        panel_h = max(300, height - 100)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and not custom_dialog:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_g:
                    show_ground_track = not show_ground_track
                elif event.key == pygame.K_p:
                    perturbations = not perturbations
                elif event.key == pygame.K_m:
                    use_mascons = not use_mascons
                elif event.key == pygame.K_v:
                    show_mascons = not show_mascons
                elif event.key == pygame.K_e and eph is not None:
                    earth_now, _ = body_vectors(time_elapsed)
                    camera.set_view(*xyz_to_latlon(earth_now))
            elif custom_dialog and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                for fi in range(3):
                    if pygame.Rect(430, 310 + fi*58, 260, 38).collidepoint(mx, my):
                        custom_active = fi
                if pygame.Rect(430, 510, 125, 40).collidepoint(mx, my):
                    try:
                        alt, inc, speed = map(float, custom_fields)
                        if not (1.0 <= alt <= 100000.0):
                            raise ValueError("Wysokość musi być w zakresie 1–100000 km.")
                        if not (0.0 <= inc <= 180.0):
                            raise ValueError("Inklinacja musi być w zakresie 0–180°.")
                        if not (0.0 < speed <= 10.0):
                            raise ValueError("Prędkość musi być w zakresie 0–10 km/s.")
                        apply_custom(alt, inc, speed)
                    except ValueError as exc:
                        custom_error = str(exc) if str(exc) else "Wprowadź poprawne liczby."
                elif pygame.Rect(565, 510, 125, 40).collidepoint(mx, my):
                    custom_dialog = False
                continue
            elif custom_dialog and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    custom_dialog = False
                elif event.key == pygame.K_TAB:
                    custom_active = (custom_active + 1) % 3
                elif event.key == pygame.K_RETURN:
                    try:
                        alt, inc, speed = map(float, custom_fields)
                        if not (1.0 <= alt <= 100000.0 and 0.0 <= inc <= 180.0 and 0.0 < speed <= 10.0):
                            raise ValueError("Poza dozwolonym zakresem.")
                        apply_custom(alt, inc, speed)
                    except ValueError:
                        custom_error = "Niepoprawne dane lub wartości poza zakresem."
                elif event.key == pygame.K_BACKSPACE:
                    custom_fields[custom_active] = custom_fields[custom_active][:-1]
                else:
                    ch = event.unicode
                    if ch and ch in "0123456789.-" and len(custom_fields[custom_active]) < 14:
                        custom_fields[custom_active] += ch
                continue
            elif slider.handle_event(event):
                continue
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    mx, my = event.pos
                    clicked = False
                    for i, (label, key) in enumerate(presets):
                        rect = pygame.Rect(25 + i*137, 20, 128, 34)
                        if rect.collidepoint(mx, my):
                            if key == "CUSTOM":
                                custom_dialog = True
                                custom_error = ""
                            else:
                                reset_sim(key)
                            clicked = True
                            break
                    if not clicked and mx < panel_x and my > 65:
                        dragging_cam = True
                        last_mouse = event.pos
                elif event.button == 4:
                    camera.zoom(0.9)
                elif event.button == 5:
                    camera.zoom(1.1)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                dragging_cam = False
            elif event.type == pygame.MOUSEMOTION and dragging_cam:
                dx = event.pos[0] - last_mouse[0]
                dy = event.pos[1] - last_mouse[1]
                last_mouse = event.pos
                deg_per_px = 0.25 * min(1.0, max(0.08, (camera.dist - R_MOON) / 4000.0))
                camera.set_view(camera.lat + dy*deg_per_px, camera.lon - dx*deg_per_px)

        if not crashed and not paused:
            sim_dt = slider.val * dt_real
            if eph is not None and epoch_s + time_elapsed + sim_dt > eph.t_max:
                crashed = True
                crash_reason = "Koniec danych efemeryd (2100-01-01 00:00 UTC)"
            else:
                n_steps = max(1, int(math.ceil(sim_dt / MAX_STEP)))
                step = sim_dt / n_steps
                use_third_body = eph is not None and perturbations
                if use_third_body:
                    earth0, sun0 = body_vectors(time_elapsed)
                    earth1, sun1 = body_vectors(time_elapsed + sim_dt)
                else:
                    earth0 = sun0 = earth1 = sun1 = zero3
                samples = np.empty((n_steps + 1, 4), dtype=np.float64)
                status, time_elapsed, n_samples = propagate(
                    state, time_elapsed, n_steps, step,
                    use_mascons, use_third_body,
                    earth0, earth1, sun0, sun1, last_sample, samples)
                if n_samples:
                    track.extend(samples[:n_samples])
                if status == STATUS_CRASH:
                    crashed, crash_reason = True, "Zderzenie z powierzchnią Księżyca"
                elif status == STATUS_ESCAPE:
                    crashed, crash_reason = True, "Sonda uciekła poza obszar symulacji"
                elif status == STATUS_NAN:
                    crashed, crash_reason = True, "Błąd numeryczny — stan nie jest skończony"

            pos_now, vel_now = state[:3], state[3:]
            history_alt.append(float(np.linalg.norm(pos_now) - R_MOON))
            history_vel.append(float(np.linalg.norm(inertial_velocity(pos_now, vel_now))))
            if len(history_alt) > max_history:
                history_alt.pop(0)
                history_vel.pop(0)

        pos = state[:3].copy()
        vel = state[3:].copy()
        earth_body, sun_body = body_vectors(time_elapsed)
        sun_dir = None if sun_body is None else sun_body / np.linalg.norm(sun_body)
        subsolar = None if sun_body is None else xyz_to_latlon(sun_body)
        subearth = None if earth_body is None else xyz_to_latlon(earth_body)

        # ------------------------------- RENDER -------------------------------
        screen.fill((10, 13, 20))
        view_cx = int(panel_x*0.48)
        view_cy = int(height*0.53)
        focal = min(panel_x, height)*0.92
        center = (view_cx, view_cy)
        view_rect = pygame.Rect(0, 0, panel_x, height)

        if fit_pending:
            r_max = orbit_extent(state[:3], state[3:])
            camera.dist = min(OrbitCamera.MAX_DIST,
                              max(6000.0, r_max * (1.0 + focal / (0.42 * height))))
            fit_pending = False

        screen.set_clip(view_rect)
        render_textured_moon(screen, camera, center, focal, texture, sun_dir, view_rect)
        label_bounds = pygame.Rect(0, 62, panel_x - 10, height - 62 - 80)
        draw_lunar_grid_and_landmarks(screen, camera, center, focal, font, label_bounds)
        if show_mascons:
            draw_mascon_overlays_3d(screen, camera, center, focal, font_small, label_bounds)

        track_pts = track.view()
        if show_ground_track and track_pts.shape[0] > 1:
            dirs = track_pts[:, :3] / np.linalg.norm(track_pts[:, :3], axis=1)[:, None]
            ground = dirs * (R_MOON * 1.003)
            gx, gy, _ = camera.project(ground, view_cx, view_cy, focal)
            draw_runs(screen, (255, 170, 60), gx, gy, camera.visible(ground), width=2)

        for point, marker in ((sun_body, draw_sun_marker), (earth_body, draw_earth_marker)):
            if point is not None and camera.apparent_radius(focal) >= 25:
                surf_pt = point / np.linalg.norm(point) * R_MOON * 1.01
                if camera.visible(surf_pt)[0]:
                    mx_, my_, _ = camera.project(surf_pt, view_cx, view_cy, focal)
                    marker(screen, int(mx_[0]), int(my_[0]), 7)

        if track_pts.shape[0] > 1:
            ox, oy, _ = camera.project(track_pts[:, :3], view_cx, view_cy, focal)
            draw_runs(screen, (100, 200, 255), ox, oy, camera.visible(track_pts[:, :3]))

        sat_visible = bool(camera.visible(pos)[0])
        sx_, sy_, _ = camera.project(pos, view_cx, view_cy, focal)
        sat_xy = (int(sx_[0]), int(sy_[0]))
        nadir = pos / np.linalg.norm(pos) * R_MOON * 1.003
        if show_ground_track and camera.visible(nadir)[0]:
            nx_, ny_, _ = camera.project(nadir, view_cx, view_cy, focal)
            nadir_xy = (int(nx_[0]), int(ny_[0]))
            if sat_visible:
                pygame.draw.line(screen, (200, 200, 120), sat_xy, nadir_xy)
            pygame.draw.circle(screen, (10, 10, 10), nadir_xy, 5)
            pygame.draw.circle(screen, (255, 170, 60), nadir_xy, 4, 2)
        if sat_visible:
            pygame.draw.circle(screen, (255, 80, 80) if crashed else (255, 220, 80), sat_xy, 6)
            screen.blit(font.render("Sonda", True, (255, 255, 255)), (sat_xy[0]+10, sat_xy[1]-10))
        screen.set_clip(None)

        bottom_bar = pygame.Surface((panel_x, 86), pygame.SRCALPHA)
        bottom_bar.fill((10, 13, 20, 170))
        screen.blit(bottom_bar, (0, height - 86))

        for i, (label, key) in enumerate(presets):
            rect = pygame.Rect(25 + i*137, 20, 128, 34)
            active = current_preset == key
            color = (50, 120, 190) if active else (30, 36, 48)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            pygame.draw.rect(screen, (80, 150, 230), rect, 1, border_radius=6)
            txt = font.render(label, True, (240, 245, 255))
            screen.blit(txt, (rect.centerx - txt.get_width()//2, rect.y + 9))

        help_lines = ["LPM: obrót  scroll: zoom  SPACJA: pauza  E: Ziemia",
                      "G: tor  P: 3. ciało  M: mascony (fizyka)  V: mapa masconów"]
        for i, line in enumerate(help_lines):
            screen.blit(font.render(line, True, (150, 160, 175)), (355, height - 72 + i*20))

        # Panel telemetrii
        panel_rect = pygame.Rect(panel_x, panel_top, panel_w, panel_h)
        pygame.draw.rect(screen, (16, 20, 28), panel_rect, border_radius=8)
        pygame.draw.rect(screen, (45, 55, 75), panel_rect, 1, border_radius=8)

        altitude = float(np.linalg.norm(pos) - R_MOON)
        speed = float(np.linalg.norm(inertial_velocity(pos, vel)))
        hp, ha, ecc, _ = osculating_elements(pos, vel)
        sub_lat, sub_lon = xyz_to_latlon(pos)
        dg_rad, dg_hor, near_basin = mascon_diagnostics(pos)

        if eph is not None:
            time_line = (f"UTC: {from_ephem_seconds(epoch_s + time_elapsed):%Y-%m-%d %H:%M:%S}"
                         f"   T+{time_elapsed/3600.0:.2f} h")
            r_dir = pos / np.linalg.norm(pos)
            sun_elev = math.degrees(math.asin(max(-1.0, min(1.0, float(r_dir @ sun_dir)))))
            along = float(pos @ sun_dir)
            in_shadow = along < 0 and float(np.linalg.norm(pos - along * sun_dir)) < R_MOON
            light_line = (f"Słońce nad p. podsat.: {sun_elev:+5.1f}° ({'dzień' if sun_elev > 0 else 'noc'})"
                          f"  sonda: {'w cieniu' if in_shadow else 'w słońcu'}")
        else:
            time_line = f"Czas: T+{time_elapsed/3600.0:.3f} h (brak efemeryd)"
            light_line = "Oświetlenie: stałe (brak coords/*.csv)"

        if use_mascons:
            basin_tag = f" [{near_basin}]" if near_basin else ""
            mascon_line = f"Anomalia masconów: {dg_rad:+6.1f} mGal (poz. {dg_hor:5.1f}){basin_tag}"
            mascon_col = (255, 145, 175) if abs(dg_rad) > 25.0 else (210, 215, 225)
        else:
            mascon_line = "Anomalia masconów: WYŁĄCZONA (klawisz M)"
            mascon_col = (140, 150, 165)

        ha_str = f"{ha:,.1f}" if math.isfinite(ha) else "∞"
        model = "monopol + J2"
        if use_mascons:
            model += " + C22/J3/J4 + 14 masconów"
        if eph is not None and perturbations:
            model += " + Ziemia + Słońce"

        status_text = "PAUZA" if paused and not crashed else (crash_reason if crashed else "SYMULACJA AKTYWNA")
        lines = [
            ("--- TELEMETRIA ---", (210, 215, 225)),
            (f"Preset: {current_preset}", (210, 215, 225)),
            (time_line, (210, 215, 225)),
            (f"Wysokość: {altitude:,.2f} km   Prędkość: {speed:.4f} km/s", (210, 215, 225)),
            (f"Orbita oskul.: {hp:,.1f} × {ha_str} km   e = {ecc:.5f}", (150, 220, 255)),
            (f"Punkt podsatelitarny: {float(sub_lat):+8.3f}°  {float(sub_lon):+9.3f}°", (255, 190, 110)),
            (mascon_line, mascon_col),
            (light_line, (210, 215, 225)),
            (f"Model: {model}", (210, 215, 225)),
            (f"Status: {status_text}", (255, 105, 105) if crashed else (210, 215, 225)),
        ]
        for i, (line, col) in enumerate(lines):
            screen.blit(font.render(line, True, col), (panel_x+16, panel_top+12+i*19))

        # Mapa toru podsatelitarnego
        panel_bottom = panel_top + panel_h
        map_title_y = panel_top + 12 + len(lines)*19 + 6
        map_w = panel_w - 32
        map_h = map_w // 2
        avail = panel_bottom - (map_title_y + 22) - 175
        if map_h > avail:
            map_h = max(60, avail)
            map_w = 2 * map_h
        map_rect = pygame.Rect(panel_x + 16, map_title_y + 22, map_w, map_h)
        screen.blit(font_bold.render("Tor podsatelitarny [lat/lon]", True, (180, 200, 220)),
                    (panel_x + 16, map_title_y))
        if np.linalg.norm(pos) > R_MOON:
            v_in = inertial_velocity(pos, vel)
            energy = 0.5 * float(v_in @ v_in) - GM_MOON / float(np.linalg.norm(pos))
            period = (2*math.pi*math.sqrt((-GM_MOON/(2*energy))**3/GM_MOON) if energy < 0 else 7*86400.0)
        else:
            period = 7*86400.0
        track_map.draw(screen, map_rect, track_pts, time_elapsed, min(period, 7*86400.0),
                       pos, sun_dir, subsolar, subearth, font_small, show_mascons=show_mascons)

        def draw_chart(title, values, x, y, w, h, line_color, unit):
            screen.blit(font_bold.render(title, True, (180, 200, 220)), (x, y))
            rect = pygame.Rect(x, y+22, w, h)
            pygame.draw.rect(screen, (8, 10, 15), rect, border_radius=4)
            pygame.draw.rect(screen, (45, 60, 80), rect, 1, border_radius=4)
            if len(values) >= 2:
                lo = min(values)
                hi = max(values)
                lo_label, hi_label = lo, hi
                if hi-lo < 1e-9:
                    lo -= 0.5
                    hi += 0.5
                pad = (hi-lo)*0.08
                lo -= pad
                hi += pad
                pts = [
                    (rect.x + int(i/(len(values)-1)*(rect.width-2)) + 1,
                     rect.bottom - 1 - int((v-lo)/(hi-lo)*(rect.height-2)))
                    for i, v in enumerate(values)
                ]
                pygame.draw.aalines(screen, line_color, False, pts)
                screen.blit(font_small.render(f"{hi_label:,.3f} {unit}", True, (145, 155, 170)),
                            (rect.x+5, rect.y+4))
                screen.blit(font_small.render(f"{lo_label:,.3f} {unit}", True, (145, 155, 170)),
                            (rect.x+5, rect.bottom-17))

        charts_y = map_rect.bottom + 22
        chart_h = max(50, min(170, panel_bottom - charts_y - 34))
        chart_w = (panel_w - 32 - 12) // 2
        draw_chart("Wysokość [km]", history_alt, panel_x + 16, charts_y, chart_w, chart_h,
                   (80, 220, 140), "km")
        draw_chart("Prędkość [km/s]", history_vel, panel_x + 28 + chart_w, charts_y, chart_w, chart_h,
                   (250, 160, 60), "km/s")

        slider.draw(screen, font)
        if texture is None:
            hint = font.render("Brak tekstury — umieść plik w Textures/moon_texture8K.jpg",
                               True, (255, 190, 100))
            screen.blit(hint, (25, height-100))

        if custom_dialog:
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 175))
            screen.blit(overlay, (0, 0))
            box = pygame.Rect(390, 245, 320, 335)
            pygame.draw.rect(screen, (22, 29, 42), box, border_radius=10)
            pygame.draw.rect(screen, (90, 135, 185), box, 2, border_radius=10)
            screen.blit(font_bold.render("CUSTOM ORBIT", True, (240,245,255)), (420, 265))
            labels = ["Wysokość [km]", "Inklinacja [deg]", "Prędkość [km/s]"]
            for fi, label in enumerate(labels):
                y = 310 + fi*58
                screen.blit(font.render(label, True, (205,215,230)), (420, y-21))
                rr = pygame.Rect(430, y, 260, 38)
                pygame.draw.rect(screen, (45, 58, 76) if fi == custom_active else (30, 38, 52), rr, border_radius=5)
                pygame.draw.rect(screen, (100, 165, 225), rr, 1, border_radius=5)
                screen.blit(font_bold.render(custom_fields[fi], True, (255,255,255)), (442, y+10))
            v0 = circular_speed(float(custom_fields[0])) if custom_fields[0].replace('.','',1).isdigit() and float(custom_fields[0]) > 0 else 0.0
            screen.blit(font.render(f"Sugestia: prędkość kołowa = {v0:.4f} km/s", True, (120,220,160)), (420, 490))
            pygame.draw.rect(screen, (45,115,80), (430,510,125,40), border_radius=5)
            pygame.draw.rect(screen, (65,75,95), (565,510,125,40), border_radius=5)
            screen.blit(font.render("Zastosuj", True, (255,255,255)), (460,523))
            screen.blit(font.render("Anuluj", True, (255,255,255)), (596,523))
            if custom_error:
                screen.blit(font.render(custom_error[:48], True, (255,120,120)), (420, 555))
            else:
                screen.blit(font.render("TAB: następne pole | ENTER: zastosuj | ESC: wyjście", True, (175,185,200)), (405, 555))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
