#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Symulator orbit wokół Księżyca: model grawitacyjny + wizualizacja teksturowanej sfery.
Wymagane: numpy, pygame, numba
Uruchomienie: python3 lunar_simulator.py
Teksturę umieść w ./Textures/moon_texture8K.jpg (lub obok skryptu).
"""

import os
import sys
import math
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

J2 = 2.0329e-4
# Demonstracyjny model anomalii masconów. To NIE są rzeczywiste masy ani
# model geofizyczny; lokalne zaburzenia opisuje gładki potencjał Gaussa.
# Włączany wyłącznie w presecie "MASCON collision demonstrator".
MASCON_CENTERS = np.radians(np.array([
    [32.8, -15.6],   # Mare Imbrium: szerokość, długość [deg]
    [28.0,  17.5],   # Mare Serenitatis
    [17.0,  59.1],   # Mare Crisium
    [-19.4, -92.8],  # Orientale
], dtype=np.float64))
MASCON_AMPLITUDES = np.array([0.018, 0.012, 0.010, 0.014], dtype=np.float64)  # km^2/s^2
MASCON_SIGMA = 180.0  # km; szerokość anomalii, celowo wygładzona


# Punkty orientacyjne na powierzchni Księżyca. Współrzędne: planetocentryczne,
# szerokość geograficzna i długość wschodnia w stopniach. Dla lokalizacji
# historycznych stosujemy punkt lądowania/końcowego położenia łazika, jeśli jest znany.
# Shackleton i dokładne położenia biegunów są oznaczeniami orientacyjnymi.
LUNAR_LANDMARKS = [
    # Bieguny i cel eksploracji południowego bieguna
    ("Biegun N", 90.0, 0.0, "pole"),
    ("Biegun S", -90.0, 0.0, "pole"),
    ("Shackleton", -89.9, 0.0, "crater"),
    # Apollo — współrzędne NASA/NSSDC, układ DE421 Mean Earth/Polar Axis
    ("Apollo 11", 0.67416, 23.47314, "apollo"),
    ("Apollo 12", -3.0128, -23.4219, "apollo"),
    ("Apollo 14", -3.64589, -17.47194, "apollo"),
    ("Apollo 15", 26.13239, 3.63330, "apollo"),
    ("Apollo 16", -8.9734, 15.5011, "apollo"),
    ("Apollo 17", 20.1911, 30.7723, "apollo"),
    # Program Luna i łaziki Lunokhod — pozycje końcowe łazików, gdzie dostępne
    ("Luna 9", 7.13, -64.37, "ussr"),
    ("Luna 16", -0.5137, 56.3638, "ussr"),
    ("Lunokhod 1", 38.3150, -35.0081, "ussr"),
    ("Luna 17", 38.2376, -35.0016, "ussr"),
    ("Luna 20", 3.7863, 56.6242, "ussr"),
    ("Lunokhod 2", 25.8323, 30.9222, "ussr"),
    ("Luna 21", 25.9994, 30.4076, "ussr"),
    ("Luna 24", 12.7142, 62.2129, "ussr"),
    # Chiny, Indie i Japonia
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


@njit(cache=True)
def moon_gravity_accel(x, y, z, mascon_demo=False):
    """Przyspieszenie w układzie związanym z Księżycem [km/s^2].

    Model bazowy: centralne pole + J2. Opcjonalny tryb demonstracyjny dodaje
    gładkie, sztucznie wzmocnione anomalie Gaussa (nie dane GRAIL).
    """
    r2 = x*x + y*y + z*z
    r = math.sqrt(r2)
    if r < 1.0:
        return 0.0, 0.0, 0.0

    r3 = r2 * r
    mu_r3 = -GM_MOON / r3
    ax = mu_r3 * x
    ay = mu_r3 * y
    az = mu_r3 * z

    # Standardowy składnik J2.
    zr2 = (z / r) ** 2
    j = 1.5 * J2 * (R_MOON / r) ** 2
    ax += mu_r3 * j * x * (5.0 * zr2 - 1.0)
    ay += mu_r3 * j * y * (5.0 * zr2 - 1.0)
    az += mu_r3 * j * z * (5.0 * zr2 - 3.0)

    # Opcjonalny model dydaktyczny: potencjał U=-A exp(-d^2/2sigma^2).
    # Daje gładkie, skończone przyspieszenie, bez osobliwości punktowej.
    if mascon_demo:
        sigma2 = MASCON_SIGMA * MASCON_SIGMA
        rm = R_MOON - 30.0
        for i in range(MASCON_CENTERS.shape[0]):
            lat = MASCON_CENTERS[i, 0]
            lon = MASCON_CENTERS[i, 1]
            mx = rm * math.cos(lat) * math.cos(lon)
            my = rm * math.cos(lat) * math.sin(lon)
            mz = rm * math.sin(lat)
            dx, dy, dz = x-mx, y-my, z-mz
            d2 = dx*dx + dy*dy + dz*dz
            e = math.exp(-0.5*d2/sigma2)
            fac = -MASCON_AMPLITUDES[i] * e / sigma2
            ax += fac*dx
            ay += fac*dy
            az += fac*dz

    return ax, ay, az


@njit(cache=True)
def derivatives(x, y, z, vx, vy, vz, mascon_demo=False):
    ax, ay, az = moon_gravity_accel(x, y, z, mascon_demo)
    # Układ obracający się z Księżycem:
    # a_cor = -2 omega x v; a_cent = -omega x (omega x r).
    w = OMEGA_MOON
    ax += w*w*x + 2.0*w*vy
    ay += w*w*y - 2.0*w*vx
    return vx, vy, vz, ax, ay, az


@njit(cache=True)
def rk4_step(x, y, z, vx, vy, vz, dt, mascon_demo=False):
    k1 = derivatives(x, y, z, vx, vy, vz, mascon_demo)
    k2 = derivatives(
        x + 0.5*dt*k1[0], y + 0.5*dt*k1[1], z + 0.5*dt*k1[2],
        vx + 0.5*dt*k1[3], vy + 0.5*dt*k1[4], vz + 0.5*dt*k1[5], mascon_demo)
    k3 = derivatives(
        x + 0.5*dt*k2[0], y + 0.5*dt*k2[1], z + 0.5*dt*k2[2],
        vx + 0.5*dt*k2[3], vy + 0.5*dt*k2[4], vz + 0.5*dt*k2[5], mascon_demo)
    k4 = derivatives(
        x + dt*k3[0], y + dt*k3[1], z + dt*k3[2],
        vx + dt*k3[3], vy + dt*k3[4], vz + dt*k3[5], mascon_demo)

    return (
        x + dt*(k1[0] + 2*k2[0] + 2*k3[0] + k4[0])/6.0,
        y + dt*(k1[1] + 2*k2[1] + 2*k3[1] + k4[1])/6.0,
        z + dt*(k1[2] + 2*k2[2] + 2*k3[2] + k4[2])/6.0,
        vx + dt*(k1[3] + 2*k2[3] + 2*k3[3] + k4[3])/6.0,
        vy + dt*(k1[4] + 2*k2[4] + 2*k3[4] + k4[4])/6.0,
        vz + dt*(k1[5] + 2*k2[5] + 2*k3[5] + k4[5])/6.0,
    )


def orbital_state(altitude_km, inclination_deg, speed_kms, true_anomaly_deg=0.0,
                  latitude_deg=0.0, longitude_deg=0.0):
    """Stan w układzie obracającym się z Księżycem.

    Dla zwykłych presetów punkt startu leży na równiku (lat/lon=0).
    Dla demonstratora można ustawić punkt startu nad konkretnym mare.
    """
    r = R_MOON + altitude_km
    inc = math.radians(inclination_deg)
    nu = math.radians(true_anomaly_deg)
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


def circular_speed(altitude_km):
    return math.sqrt(GM_MOON / (R_MOON + altitude_km))


def get_preset_orbit(name):
    if name == "LRO":
        # LRO: około kołowa orbita polarna, 50 km; w rzeczywistości wymaga station-keeping.
        return orbital_state(50.0, 90.0, circular_speed(50.0))
    if name == "Gateway":
        # Wizualizacyjny seed o dużej ekscentryczności. To nie jest dokładny NRHO
        # z efemerydy Gateway: do tego potrzebne są warunki początkowe CR3BP/ephemeris.
        rp, ra = R_MOON + 3000.0, R_MOON + 70000.0
        a = 0.5*(rp+ra)
        vp = math.sqrt(GM_MOON*(2.0/rp - 1.0/a))
        return orbital_state(3000.0, 90.0, vp)
    if name == "Luna 10":
        # Historyczna orbita w przybliżeniu: 350 x 1016 km, i ~71.9 deg.
        rp, ra = R_MOON + 350.0, R_MOON + 1016.0
        a = 0.5*(rp+ra)
        vp = math.sqrt(GM_MOON*(2.0/rp - 1.0/a))
        return orbital_state(350.0, 71.9, vp)
    if name == "MASCON collision demonstrator":
        # Sonda startuje nad Mare Imbrium z prędkością mniejszą od kołowej.
        # Zderzenie jest celowo wymuszone; anomalie są poglądowe i wzmocnione.
        v = 0.82*circular_speed(90.0)
        return orbital_state(90.0, 25.0, v,
                             latitude_deg=32.8, longitude_deg=-15.6)
    # Bezpieczny fallback.
    return orbital_state(100.0, 45.0, circular_speed(100.0))


# ------------------------------- TEKSTURA -------------------------------

def find_texture():
    """Szuka tekstury względem katalogu skryptu i bieżącego katalogu."""
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
    # Można wskazać własny plik: MOON_TEXTURE=/ścieżka/do/pliku.jpg
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
        # Ograniczenie rozmiaru przyspiesza mapowanie, zachowując szczegóły.
        max_width = 4096
        if image.get_width() > max_width:
            h = max(1, round(image.get_height() * max_width / image.get_width()))
            image = pygame.transform.smoothscale(image, (max_width, h))
        # array3d ma kolejność [x, y, kanał] — indeksowanie poniżej jest zgodne.
        pixels = pygame.surfarray.array3d(image)
        print(f"[OK] Tekstura załadowana: {image.get_width()} x {image.get_height()}")
        return pixels
    except (pygame.error, OSError) as exc:
        print(f"[ERROR] Nie udało się wczytać tekstury: {exc}")
        return None


def render_textured_moon(screen, center, focal, cam_dist, texture, cam_rx, cam_rz):
    """Renderuje Księżyc przez perspektywiczne przecięcie promieni z kulą.

    Konwencja mapy equirectangularnej:
      * środek obrazu w poziomie = lon 0 deg,
      * prawa strona = dodatnia długość (E),
      * góra obrazu = biegun N (lat +90 deg),
      * dół obrazu = biegun S (lat -90 deg).

    Najpierw odtwarzamy punkt powierzchni w układzie kamery, a następnie
    stosujemy dokładną odwrotność tej samej rotacji, której używa project().
    Dzięki temu tekstura, siatka i znaczniki korzystają z jednego układu.
    """
    cx, cy = center
    if cam_dist <= R_MOON or focal <= 0:
        return

    # Promień obrazu stycznego do widocznej kuli w rzucie perspektywicznym.
    apparent_radius = int(math.ceil(focal * R_MOON /
                                     math.sqrt(cam_dist*cam_dist - R_MOON*R_MOON)))
    if apparent_radius < 2:
        pygame.draw.circle(screen, (145, 145, 150), center, max(1, apparent_radius))
        return

    if texture is None:
        pygame.draw.circle(screen, (125, 125, 130), center, apparent_radius)
        pygame.draw.circle(screen, (185, 185, 190), center, apparent_radius, 1)
        return

    # Współrzędne pikseli względem środka obrazu. Kamera patrzy wzdłuż +Zc;
    # jej środek znajduje się w (0, 0, -cam_dist).
    extent = apparent_radius + 2
    yy, xx = np.mgrid[-extent:extent+1, -extent:extent+1]
    qx = xx.astype(np.float64) / focal
    qy = -yy.astype(np.float64) / focal
    qa = qx*qx + qy*qy + 1.0

    # | O + t*q |^2 = R^2, O=(0,0,-cam_dist). Bierzemy bliższy
    # dodatni pierwiastek — punkt na widocznej półkuli.
    discriminant = cam_dist*cam_dist - qa*(cam_dist*cam_dist - R_MOON*R_MOON)
    mask = discriminant >= 0.0
    root = np.sqrt(np.maximum(discriminant, 0.0))
    t = (cam_dist - root) / qa

    xc = t*qx
    yc = t*qy
    zc = -cam_dist + t

    # project(): R = Rx(cam_rx) * Rz(cam_rz).
    # Odwrotność: R^-1 = Rz(-cam_rz) * Rx(-cam_rx).
    crx, srx = math.cos(cam_rx), math.sin(cam_rx)
    crz, srz = math.cos(cam_rz), math.sin(cam_rz)

    # Najpierw Rx(-cam_rx), potem Rz(-cam_rz).
    y_rot = yc*crx + zc*srx
    z_world = -yc*srx + zc*crx
    x_world = xc*crz + y_rot*srz
    y_world = -xc*srz + y_rot*crz

    # Planetocentryczne współrzędne geograficzne w tym samym układzie XYZ,
    # w którym zdefiniowane są punkty LUNAR_LANDMARKS.
    lat = np.arcsin(np.clip(z_world / R_MOON, -1.0, 1.0))
    lon = np.arctan2(y_world, x_world)

    tex_w, tex_h = texture.shape[0], texture.shape[1]
    # Equirectangular: lon=-180° po lewej, lon=0° w środku,
    # lon=+180° po prawej; lat=+90° na górnej krawędzi.
    u = np.mod((lon + math.pi) / (2.0*math.pi), 1.0) * tex_w
    v = (math.pi/2.0 - lat) / math.pi * (tex_h - 1)
    ui = np.clip(u.astype(np.int32), 0, tex_w-1)
    vi = np.clip(v.astype(np.int32), 0, tex_h-1)

    sampled = texture[ui, vi].astype(np.float32)

    # Oświetlenie stałe w układzie księżycowym, a nie ekranowym:
    # obracanie kamery nie przesuwa światła względem powierzchni.
    light_world = np.array([0.35, -0.25, 0.90], dtype=np.float64)
    light_world /= np.linalg.norm(light_world)
    nxw, nyw, nzw = x_world/R_MOON, y_world/R_MOON, z_world/R_MOON
    illumination = np.clip(0.22 + 0.78*np.maximum(
        0.0, nxw*light_world[0] + nyw*light_world[1] + nzw*light_world[2]),
        0.16, 1.0)
    sampled *= illumination[..., None]
    sampled = np.clip(sampled, 0, 255).astype(np.uint8)

    surface = pygame.Surface((2*extent+1, 2*extent+1))
    out = pygame.surfarray.pixels3d(surface)
    out[:] = 0
    out[mask] = sampled[mask]
    del out
    screen.blit(surface, (cx-extent, cy-extent))
    pygame.draw.circle(screen, (175, 180, 190), center, apparent_radius, 1)


def draw_lunar_grid_and_landmarks(screen, project, cam_rx, cam_rz, font_small):
    """Nakłada siatkę geograficzną i punkty orientacyjne na widoczną półkulę."""
    crx, srx = math.cos(cam_rx), math.sin(cam_rx)
    crz, srz = math.cos(cam_rz), math.sin(cam_rz)

    def point(lat_deg, lon_deg, radius=R_MOON * 1.004):
        lat, lon = math.radians(lat_deg), math.radians(lon_deg)
        cl = math.cos(lat)
        xyz = (radius*cl*math.cos(lon), radius*cl*math.sin(lon), radius*math.sin(lat))
        x, y, z = xyz
        x1 = x*crz - y*srz
        y1 = x*srz + y*crz
        z2 = y1*srx + z*crx
        # Kamera znajduje się po stronie z_cam < 0 i patrzy w kierunku +Z.
        # Widoczna jest więc półkula z2 < 0 (nie z2 > 0).
        if z2 >= 0.0:
            return None
        p = project(xyz)
        if p is None:
            return None
        return (p[0], p[1])

    def draw_curve(coords, color, width=1):
        segment = []
        for lat, lon in coords:
            q = point(lat, lon)
            if q is None:
                if len(segment) >= 2:
                    pygame.draw.aalines(screen, color, False, segment)
                segment = []
            else:
                segment.append(q)
        if len(segment) >= 2:
            pygame.draw.aalines(screen, color, False, segment)

    # Równoleżniki co 15° (bez samych biegunów) i południki co 15°.
    grid_color = (95, 155, 175)
    for lat in range(-75, 76, 15):
        draw_curve([(float(lat), float(lon)) for lon in range(-180, 181, 3)], grid_color)
    for lon in range(-180, 180, 15):
        draw_curve([(float(lat), float(lon)) for lat in range(-90, 91, 3)], grid_color)

    # Znaczniki i podpisy. Podpisy mają ciemny cień, by pozostały czytelne na teksturze.
    for name, lat, lon, category in LUNAR_LANDMARKS:
        q = point(lat, lon, R_MOON * 1.012)
        if q is None:
            continue
        x, y = q
        color = LANDMARK_COLORS.get(category, (255, 255, 255))
        pygame.draw.circle(screen, (8, 12, 18), (x, y), 5)
        pygame.draw.circle(screen, color, (x, y), 3)
        label = font_small.render(name, True, color)
        lx, ly = x + 7, y - label.get_height() // 2
        # Nie rysuj etykiety poza obszarem globu / pod panelem telemetrii.
        if lx + label.get_width() < screen.get_width() * 0.55 and 70 < ly < screen.get_height() - 65:
            shadow = font_small.render(name, True, (5, 8, 12))
            screen.blit(shadow, (lx+1, ly+1))
            screen.blit(label, (lx, ly))


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


def main():
    pygame.init()
    pygame.display.set_caption("Lunar Orbiter Simulator — teksturowany Księżyc")
    screen = pygame.display.set_mode((1400, 900), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("DejaVu Sans Mono", 14)
    font_bold = pygame.font.SysFont("DejaVu Sans Mono", 15, bold=True)

    texture = load_texture()

    presets = [
        ("LRO", "LRO"),
        ("Gateway", "Gateway"),
        ("Luna 10", "Luna 10"),
        ("MASCON collision", "MASCON collision demonstrator"),
        ("Custom", "CUSTOM"),
    ]

    current_preset = "LRO"
    pos, vel = get_preset_orbit(current_preset)
    custom_dialog = False
    custom_fields = ["100", "45", f"{circular_speed(100.0):.4f}"]
    custom_active = 0
    custom_error = ""
    trail = []
    max_trail_len = 3000
    history_alt, history_vel = [], []
    max_history = 240
    time_elapsed = 0.0
    crashed = False
    crash_reason = ""
    paused = False

    cam_dist = 6000.0
    cam_rot_x = math.radians(25.0)
    cam_rot_z = math.radians(35.0)
    dragging_cam = False
    last_mouse = (0, 0)
    slider = TimeSlider(30, 845, 300, 10, 1.0, 100000.0, 30.0, "Tempo symulacji")

    def reset_sim(preset=None):
        nonlocal pos, vel, current_preset, time_elapsed, crashed, crash_reason
        if preset and preset != "RESET":
            current_preset = preset
        pos, vel = get_preset_orbit(current_preset)
        trail.clear()
        history_alt.clear()
        history_vel.clear()
        time_elapsed = 0.0
        crashed = False
        crash_reason = ""

    def project(point, view_cx, view_cy, focal):
        x, y, z = point
        crz, srz = math.cos(cam_rot_z), math.sin(cam_rot_z)
        crx, srx = math.cos(cam_rot_x), math.sin(cam_rot_x)
        x1 = x*crz - y*srz
        y1 = x*srz + y*crz
        y2 = y1*crx - z*srx
        z2 = y1*srx + z*crx
        depth = cam_dist + z2
        if depth <= 1.0:
            return None
        return (int(view_cx + x1*focal/depth),
                int(view_cy - y2*focal/depth), depth)

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
                        pos, vel = orbital_state(alt, inc, speed)
                        current_preset = "Custom"
                        trail.clear(); history_alt.clear(); history_vel.clear()
                        time_elapsed = 0.0; crashed = False; crash_reason = ""
                        custom_dialog = False
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
                        pos, vel = orbital_state(alt, inc, speed)
                        current_preset = "Custom"
                        trail.clear(); history_alt.clear(); history_vel.clear()
                        time_elapsed = 0.0; crashed = False; crash_reason = ""
                        custom_dialog = False
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
                    cam_dist = max(R_MOON*1.35, cam_dist*0.9)
                elif event.button == 5:
                    cam_dist = min(100000.0, cam_dist*1.1)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                dragging_cam = False
            elif event.type == pygame.MOUSEMOTION and dragging_cam:
                dx = event.pos[0] - last_mouse[0]
                dy = event.pos[1] - last_mouse[1]
                last_mouse = event.pos
                cam_rot_z -= dx*0.005
                cam_rot_x = max(-math.pi/2 + 0.01,
                                min(math.pi/2 - 0.01, cam_rot_x + dy*0.005))

        # Integracja z ograniczeniem kroku czasowego dla stabilności.
        if not crashed and not paused:
            sim_dt = slider.val * dt_real
            # Maksymalny krok 2 s; co najmniej jeden krok.
            n_steps = max(1, int(math.ceil(sim_dt / 2.0)))
            step = sim_dt / n_steps
            for _ in range(n_steps):
                state = rk4_step(*pos, *vel, step,
                                 current_preset == "MASCON collision demonstrator")
                pos = np.array(state[:3], dtype=np.float64)
                vel = np.array(state[3:], dtype=np.float64)
                time_elapsed += step
                radius_now = float(np.linalg.norm(pos))
                if not np.all(np.isfinite(pos)) or not np.all(np.isfinite(vel)):
                    crashed = True
                    crash_reason = "Błąd numeryczny — stan nie jest skończony"
                    break
                if radius_now <= R_MOON:
                    crashed = True
                    crash_reason = "Zderzenie z powierzchnią Księżyca"
                    break
                if radius_now > 120000.0:
                    crashed = True
                    crash_reason = "Sonda uciekła poza obszar symulacji"
                    break

            trail.append(pos.copy())
            if len(trail) > max_trail_len:
                trail.pop(0)
            altitude = float(np.linalg.norm(pos) - R_MOON)
            speed = float(np.linalg.norm(vel))
            history_alt.append(altitude)
            history_vel.append(speed)
            if len(history_alt) > max_history:
                history_alt.pop(0)
                history_vel.pop(0)

        # ------------------------------- RENDER -------------------------------
        screen.fill((10, 13, 20))
        for i, (label, key) in enumerate(presets):
            rect = pygame.Rect(25 + i*137, 20, 128, 34)
            active = current_preset == key
            color = (50, 120, 190) if active else (30, 36, 48)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            pygame.draw.rect(screen, (80, 150, 230), rect, 1, border_radius=6)
            txt = font.render(label, True, (240, 245, 255))
            screen.blit(txt, (rect.centerx - txt.get_width()//2, rect.y + 9))

        view_cx = int(panel_x*0.48)
        view_cy = int(height*0.53)
        focal = min(panel_x, height)*0.92
        center_proj = project((0.0, 0.0, 0.0), view_cx, view_cy, focal)
        if center_proj:
            mx, my, depth = center_proj
            render_textured_moon(screen, (mx, my), focal, cam_dist, texture,
                                 cam_rot_x, cam_rot_z)

            def project_surface(point_xyz):
                return project(point_xyz, view_cx, view_cy, focal)

            draw_lunar_grid_and_landmarks(screen, project_surface,
                                          cam_rot_x, cam_rot_z, font)

        # Orbita: rysuj odcinki tylko dla punktów przed kamerą.
        if len(trail) > 1:
            projected = []
            for point in trail:
                p = project(point, view_cx, view_cy, focal)
                if p is not None:
                    projected.append((p[0], p[1]))
            if len(projected) > 1:
                pygame.draw.aalines(screen, (100, 200, 255), False, projected)

        sat = project(pos, view_cx, view_cy, focal)
        if sat:
            sx, sy, _ = sat
            pygame.draw.circle(screen, (255, 80, 80) if crashed else (255, 220, 80),
                               (sx, sy), 6)
            screen.blit(font.render("Sonda", True, (255, 255, 255)), (sx+10, sy-10))

        # Panel telemetrii.
        panel_rect = pygame.Rect(panel_x, panel_top, panel_w, panel_h)
        pygame.draw.rect(screen, (16, 20, 28), panel_rect, border_radius=8)
        pygame.draw.rect(screen, (45, 55, 75), panel_rect, 1, border_radius=8)

        altitude = float(np.linalg.norm(pos) - R_MOON)
        speed = float(np.linalg.norm(vel))
        status = crash_reason if crashed else "SYMULACJA AKTYWNA"
        lines = [
            "--- TELEMETRIA ---",
            f"Preset: {current_preset}",
            f"Czas: {time_elapsed/3600.0:.3f} h",
            f"Wysokość: {altitude:,.2f} km",
            f"Prędkość: {speed:.4f} km/s",
            f"Status: {status if not paused else 'PAUZA'}",
            ("Model: demonstracyjne anomalie masconów" if current_preset == "MASCON collision demonstrator" else "Model: centralny + J2"),
            "SPACJA: pauza / wznowienie",
            "LPM + przeciąganie: obrót kamery",
            "Scroll: przybliżenie / oddalenie",
            "Siatka: 15° | punkty: Apollo, Luna, Chang'e, bieguny",
        ]
        for i, line in enumerate(lines):
            col = (255, 105, 105) if crashed and i == 5 else (210, 215, 225)
            screen.blit(font.render(line, True, col), (panel_x+16, panel_top+15+i*22))

        def draw_chart(title, values, y, line_color, unit):
            chart_title = font_bold.render(title, True, (180, 200, 220))
            screen.blit(chart_title, (panel_x+16, y))
            rect = pygame.Rect(panel_x+16, y+24, max(100, panel_w-32), 145)
            pygame.draw.rect(screen, (8, 10, 15), rect, border_radius=4)
            pygame.draw.rect(screen, (45, 60, 80), rect, 1, border_radius=4)
            if len(values) >= 2:
                lo = min(values)
                hi = max(values)
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
                screen.blit(font.render(f"{hi:.3f} {unit}", True, (145, 155, 170)),
                            (rect.x+5, rect.y+4))
                screen.blit(font.render(f"{lo:.3f} {unit}", True, (145, 155, 170)),
                            (rect.x+5, rect.bottom-19))

        chart1_y = panel_top + 240
        draw_chart("Wysokość nad powierzchnią [km]", history_alt,
                   chart1_y, (80, 220, 140), "km")
        chart2_y = chart1_y + 195
        draw_chart("Prędkość orbitalna [km/s]", history_vel,
                   chart2_y, (250, 160, 60), "km/s")

        slider.draw(screen, font)
        if texture is None:
            hint = font.render("Brak tekstury — umieść plik w Textures/moon_texture8K.jpg",
                               True, (255, 190, 100))
            screen.blit(hint, (25, height-78))

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

