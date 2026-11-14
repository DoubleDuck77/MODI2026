import os
import sys
import math
import numpy as np
import pandas as pd
import pygame

# --- STAŁE ASTRONOMICZNE ---
R_MOON = 1737.4  # Promień Księżyca w km
R_EARTH = 6371.0 # Promień Ziemi w km
R_SUN = 696340.0 # Promień Słońca w km

I_MOON = math.radians(1.5424) # Nachylenie równika księżycowego do ekliptyki
SIDEREAL_MONTH = 27.321661  # dni

def load_year_data(year):
    filepath = f"Coords/{year}.csv"
    if os.path.exists(filepath):
        df = pd.read_csv(filepath)
        df['time'] = pd.to_datetime(df['time'])
        print(f"[OK] Wczytano dane dla roku {year} z: {filepath}")
    else:
        print(f"[OSTRZEŻENIE] Nie znaleziono '{filepath}'. Generuję dane testowe dla roku {year}...")
        times = pd.date_range(f"{year}-01-01 00:00:00", f"{year+1}-01-01 00:00:00", freq="h", inclusive="left")
        t_days = (times - pd.Timestamp("2000-01-01 12:00:00")).total_seconds() / 86400.0
        
        w_sun = 2 * np.pi / 365.256
        sun_x = 1.496e8 * np.cos(w_sun * t_days + 1.74)
        sun_y = 1.496e8 * np.sin(w_sun * t_days + 1.74)
        sun_z = np.zeros_like(t_days)
        
        w_moon = 2 * np.pi / SIDEREAL_MONTH
        inc = math.radians(5.145)
        moon_x = 384400 * np.cos(w_moon * t_days)
        moon_y = 384400 * np.sin(w_moon * t_days) * np.cos(inc)
        moon_z = 384400 * np.sin(w_moon * t_days) * np.sin(inc)
        
        df = pd.DataFrame({
            'time': times,
            'sun_x': sun_x, 'sun_y': sun_y, 'sun_z': sun_z,
            'moon_x': moon_x, 'moon_y': moon_y, 'moon_z': moon_z
        })

    j2000 = pd.Timestamp("2000-01-01 12:00:00")
    df['d_j2000_total'] = (df['time'] - j2000).dt.total_seconds() / 86400.0
    return df

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

def calculate_lagrange_points(earth_ecl, moon_ecl, sun_ecl):
    """Oblicza pozycje punktów Lagrange'a w układzie ekliptycznym J2000."""
    # Układ Ziemia - Księżyc
    mu_em = 7.342e22 / (5.972e24 + 7.342e22)
    r_em = moon_ecl - earth_ecl
    d_em = np.linalg.norm(r_em)
    u_em = r_em / d_em
    
    ecl_z = np.array([0, 0, 1])
    u_em_perp = np.cross(u_em, ecl_z)
    u_em_perp /= np.linalg.norm(u_em_perp)
         
    r_L1_em = earth_ecl + u_em * d_em * (1.0 - (mu_em/3.0)**(1/3.0))
    r_L2_em = earth_ecl + u_em * d_em * (1.0 + (mu_em/3.0)**(1/3.0))
    r_L3_em = earth_ecl - u_em * d_em * (1.0 + (5.0*mu_em/12.0))
    r_L4_em = earth_ecl + u_em * (d_em / 2.0) + u_em_perp * (d_em * math.sqrt(3)/2.0)
    r_L5_em = earth_ecl + u_em * (d_em / 2.0) - u_em_perp * (d_em * math.sqrt(3)/2.0)
    
    em_points = {'L1': r_L1_em, 'L2': r_L2_em, 'L3': r_L3_em, 'L4': r_L4_em, 'L5': r_L5_em}

    # Układ Słońce - Ziemia
    mu_se = 5.972e24 / (1.989e30 + 5.972e24)
    r_se = earth_ecl - sun_ecl
    d_se = np.linalg.norm(r_se)
    u_se = r_se / d_se
    u_se_perp = np.cross(u_se, ecl_z)
    u_se_perp /= np.linalg.norm(u_se_perp)
    
    r_L1_se = sun_ecl + u_se * d_se * (1.0 - (mu_se/3.0)**(1/3.0))
    r_L2_se = sun_ecl + u_se * d_se * (1.0 + (mu_se/3.0)**(1/3.0))
    r_L3_se = sun_ecl - u_se * d_se * (1.0 + (5.0*mu_se/12.0))
    r_L4_se = sun_ecl + u_se * (d_se / 2.0) + u_se_perp * (d_se * math.sqrt(3)/2.0)
    r_L5_se = sun_ecl + u_se * (d_se / 2.0) - u_se_perp * (d_se * math.sqrt(3)/2.0)
    
    se_points = {'L1': r_L1_se, 'L2': r_L2_se, 'L3': r_L3_se, 'L4': r_L4_se, 'L5': r_L5_se}

    return em_points, se_points

def get_topocentric_vectors(df, time_idx_float, lat_deg, lon_deg):
    idx0 = int(math.floor(time_idx_float))
    idx1 = min(idx0 + 1, len(df) - 1)
    frac = time_idx_float - idx0
    
    row0, row1 = df.iloc[idx0], df.iloc[idx1]
    d_j2000 = row0['d_j2000_total'] * (1 - frac) + row1['d_j2000_total'] * frac
    
    sun_geo = np.array([
        row0['sun_x'] * (1 - frac) + row1['sun_x'] * frac,
        row0['sun_y'] * (1 - frac) + row1['sun_y'] * frac,
        row0['sun_z'] * (1 - frac) + row1['sun_z'] * frac
    ])
    moon_geo = np.array([
        row0['moon_x'] * (1 - frac) + row1['moon_x'] * frac,
        row0['moon_y'] * (1 - frac) + row1['moon_y'] * frac,
        row0['moon_z'] * (1 - frac) + row1['moon_z'] * frac
    ])
    
    earth_ecl = np.array([0.0, 0.0, 0.0])
    moon_ecl = moon_geo
    sun_ecl = sun_geo
    
    earth_seleno_ecl = -moon_geo
    sun_seleno_ecl = sun_geo - moon_geo
    
    R_body = get_lunar_body_matrix(d_j2000)
    earth_body = R_body @ earth_seleno_ecl
    sun_body = R_body @ sun_seleno_ecl
    
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    obs_body = R_MOON * np.array([
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat)
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
    
    em_pts, se_pts = calculate_lagrange_points(earth_ecl, moon_ecl, sun_ecl)
    
    def process_lagrange_dict(pts_dict):
        result = {}
        for key, pt_ecl in pts_dict.items():
            pt_seleno_ecl = pt_ecl - moon_geo
            pt_body = R_body @ pt_seleno_ecl
            vec_obs = pt_body - obs_body
            alt, az, dist = to_alt_az(vec_obs)
            result[key] = (alt, az, dist)
        return result

    lagrange_em = process_lagrange_dict(em_pts)
    lagrange_se = process_lagrange_dict(se_pts)

    current_time = row0['time'] + (row1['time'] - row0['time']) * frac
    return {
        'time': current_time,
        'R_body': R_body,
        'earth': (earth_alt, earth_az, earth_dist),
        'sun': (sun_alt, sun_az, sun_dist),
        'obs_bases': (north, east, up),
        'sun_earth_dir': sun_earth_dir,
        'lagrange_em': lagrange_em,
        'lagrange_se': lagrange_se
    }

class Slider:
    def __init__(self, x, y, w, h, min_val, max_val, val, label, fmt="{:.2f}", is_int=False):
        self.rect = pygame.Rect(x, y, w, h)
        self.min_val, self.max_val, self.val = min_val, max_val, val
        self.label, self.fmt, self.is_int = label, fmt, is_int
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
        val = self.min_val + ratio * (self.max_val - self.min_val)
        self.val = int(round(val)) if self.is_int else val

    def draw(self, screen, font, custom_text=None):
        pygame.draw.rect(screen, (60, 65, 75), self.rect, border_radius=4)
        ratio = (self.val - self.min_val) / (self.max_val - self.min_val) if self.max_val > self.min_val else 0
        fill_rect = pygame.Rect(self.rect.x, self.rect.y, int(self.rect.width * ratio), self.rect.height)
        pygame.draw.rect(screen, (100, 160, 230), fill_rect, border_radius=4)
        pygame.draw.circle(screen, (240, 245, 255), (self.rect.x + int(self.rect.width * ratio), self.rect.centery), 8)
        
        val_str = custom_text if custom_text else (str(int(self.val)) if self.is_int else self.fmt.format(self.val))
        txt = font.render(f"{self.label}: {val_str}", True, (230, 230, 230))
        screen.blit(txt, (self.rect.x, self.rect.y - 20))

def load_texture(path):
    if os.path.exists(path):
        try:
            return pygame.image.load(path).convert()
        except Exception:
            pass
    return None

def main():
    pygame.init()
    W, H = 1280, 800
    screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
    pygame.display.set_caption("Lunar Stellarium - Ziemia, Słońce i Punkty Lagrange'a")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Consolas", 15)
    font_big = pygame.font.SysFont("Consolas", 18, bold=True)

    cam_az = 0.0
    cam_alt = math.radians(25.0)
    fov = math.radians(75.0)
    
    dragging_sky = False
    last_mouse = (0, 0)
    playing = False
    play_speed = 24.0

    current_year = 2050
    df = load_year_data(current_year)

    slider_year = Slider(30, H - 45, 250, 10, 2000, 2100, current_year, "Rok", is_int=True)
    slider_time = Slider(300, H - 45, W - 330, 10, 0, len(df) - 1, 0, "Czas w roku")
    slider_lat = Slider(30, 40, 240, 10, -90.0, 90.0, 0.0, "Szerokość (Lat)", "{:+.2f}°")
    slider_lon = Slider(30, 90, 240, 10, -180.0, 180.0, 0.0, "Długość (Lon)", "{:+.2f}°")

    earth_day = load_texture("Textures/earth_day8K.jpg") or load_texture("Textures/earth_day8K.png")
    earth_night = load_texture("Textures/earth_night8K.jpg") or load_texture("Textures/earth_night8K.png")
    earth_clouds = load_texture("Textures/earth_clouds8K.jpg") or load_texture("Textures/earth_clouds8K.png")

    np.random.seed(42)
    n_stars = 1000
    star_lam = np.random.uniform(0, 2 * np.pi, n_stars)
    star_beta = np.arcsin(np.random.uniform(-1, 1, n_stars))
    star_mags = np.random.randint(90, 255, n_stars)
    
    stars_ecl = np.stack([
        np.cos(star_beta) * np.cos(star_lam),
        np.cos(star_beta) * np.sin(star_lam),
        np.sin(star_beta)
    ], axis=-1)

    def project_point(alt, az, cw, ch):
        px = math.cos(alt) * math.cos(az)
        py = math.cos(alt) * math.sin(az)
        pz = math.sin(alt)
        
        fwd = np.array([math.cos(cam_alt) * math.cos(cam_az), math.cos(cam_alt) * math.sin(cam_az), math.sin(cam_alt)])
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(fwd, world_up)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([-math.sin(cam_az), math.cos(cam_az), 0.0])
        else:
            right /= np.linalg.norm(right)
        cam_up = np.cross(right, fwd)
        
        p = np.array([px, py, pz])
        z_cam = np.dot(p, fwd)
        if z_cam <= 0.05:
            return None
            
        x_cam = np.dot(p, right)
        y_cam = np.dot(p, cam_up)
        focal = (ch / 2.0) / math.tan(fov / 2.0)
        return (cw / 2.0 + (x_cam / z_cam) * focal, ch / 2.0 - (y_cam / z_cam) * focal, z_cam, focal)

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
            if slider_time.handle_event(event) or slider_lat.handle_event(event) or slider_lon.handle_event(event):
                continue

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    dragging_sky = True
                    last_mouse = event.pos
                elif event.button == 4: fov = max(math.radians(5.0), fov * 0.85)
                elif event.button == 5: fov = min(math.radians(120.0), fov * 1.15)
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1: dragging_sky = False
            elif event.type == pygame.MOUSEMOTION and dragging_sky:
                dx, dy = event.pos[0] - last_mouse[0], event.pos[1] - last_mouse[1]
                last_mouse = event.pos
                sens = fov / ch
                cam_az = (cam_az - dx * sens) % (2 * math.pi)
                cam_alt = max(-math.pi/2 + 0.01, min(math.pi/2 - 0.01, cam_alt + dy * sens))
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE: playing = not playing
                elif event.key == pygame.K_e: cam_alt, cam_az = data['earth'][0], data['earth'][1]
                elif event.key == pygame.K_s: cam_alt, cam_az = data['sun'][0], data['sun'][1]

        if current_year != old_year:
            df = load_year_data(current_year)
            slider_time.max_val = len(df) - 1
            slider_time.val = min(slider_time.val, slider_time.max_val)

        if playing:
            slider_time.val += play_speed * dt
            if slider_time.val >= len(df) - 1:
                slider_time.val = 0

        data = get_topocentric_vectors(df, slider_time.val, slider_lat.val, slider_lon.val)
        earth_alt, earth_az, earth_dist = data['earth']
        sun_alt, sun_az, sun_dist = data['sun']
        north, east, up = data['obs_bases']
        R_body = data['R_body']
        sun_earth_dir = data['sun_earth_dir']
        lagrange_em = data['lagrange_em']
        lagrange_se = data['lagrange_se']

        screen.fill((5, 7, 12))

        # Gwiazdy
        stars_body = (R_body @ stars_ecl.T).T
        s_n = stars_body @ north
        s_e = stars_body @ east
        s_u = stars_body @ up
        
        star_alts = np.arcsin(np.clip(s_u, -1.0, 1.0))
        star_azs = np.arctan2(s_e, s_n) % (2 * np.pi)

        for s_alt, s_az, mag in zip(star_alts, star_azs, star_mags):
            if s_alt > 0:
                proj = project_point(s_alt, s_az, cw, ch)
                if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                    screen.set_at((int(proj[0]), int(proj[1])), (mag, mag, mag))

        # Siatka azymutalna
        grid_color = (25, 35, 50)
        for a_deg in range(-60, 90, 30):
            a_rad = math.radians(a_deg)
            pts = [project_point(a_rad, math.radians(z), cw, ch) for z in range(0, 365, 5)]
            pts_xy = [(p[0], p[1]) if p else None for p in pts]
            for i in range(len(pts_xy) - 1):
                if pts_xy[i] and pts_xy[i+1]:
                    pygame.draw.line(screen, grid_color, pts_xy[i], pts_xy[i+1], 1)

        # --- PUNKTY LAGRANGE'A UKŁADU ZIEMIA - KSIĘŻYC (fioletowe/różowe) ---
        for name, (l_alt, l_az, _) in lagrange_em.items():
            if l_alt > 0:
                proj = project_point(l_alt, l_az, cw, ch)
                if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                    pygame.draw.circle(screen, (220, 100, 255), (int(proj[0]), int(proj[1])), 4)
                    screen.blit(font.render(f"EM-{name}", True, (220, 140, 255)), (int(proj[0]) + 6, int(proj[1]) - 8))

        # --- PUNKTY LAGRANGE'A UKŁADU SŁOŃCE - ZIEMIA (żółto-zielone) ---
        for name, (l_alt, l_az, _) in lagrange_se.items():
            if l_alt > 0:
                proj = project_point(l_alt, l_az, cw, ch)
                if proj and 0 <= proj[0] < cw and 0 <= proj[1] < ch:
                    pygame.draw.circle(screen, (100, 255, 180), (int(proj[0]), int(proj[1])), 4)
                    screen.blit(font.render(f"SE-{name}", True, (120, 255, 200)), (int(proj[0]) + 6, int(proj[1]) - 8))

        # --- SŁOŃCE ---
        sun_proj = project_point(sun_alt, sun_az, cw, ch)
        if sun_proj:
            sx, sy, z_cam, focal = sun_proj
            r_sun = max(6, int(math.asin(min(1.0, R_SUN / sun_dist)) * focal / z_cam))
            pygame.draw.circle(screen, (255, 230, 140), (int(sx), int(sy)), r_sun + 4)
            pygame.draw.circle(screen, (255, 255, 255), (int(sx), int(sy)), r_sun)
            screen.blit(font.render("Słońce", True, (255, 230, 150)), (sx + r_sun + 6, sy - 8))

        # --- ZIEMIA Z TEKSTURAMI ---
        earth_proj = project_point(earth_alt, earth_az, cw, ch)
        if earth_proj:
            ex, ey, z_cam, focal = earth_proj
            r_earth = max(20, int(math.asin(min(1.0, R_EARTH / earth_dist)) * focal / z_cam))
            size = r_earth * 2
            earth_surf = pygame.Surface((size, size), pygame.SRCALPHA)
            
            if earth_day is not None:
                day_w, day_h = earth_day.get_size()
                night_w, night_h = earth_night.get_size() if earth_night else (0, 0)
                clouds_w, clouds_h = earth_clouds.get_size() if earth_clouds else (0, 0)
                
                for py in range(size):
                    y_norm = (py - r_earth) / r_earth
                    if y_norm**2 > 1.0: continue
                    y_sq = y_norm**2
                    for px in range(size):
                        x_norm = (px - r_earth) / r_earth
                        dist_sq = x_norm**2 + y_sq
                        if dist_sq > 1.0: continue
                        
                        z_sphere = math.sqrt(1.0 - dist_sq)
                        pt_body = np.array([z_sphere, -x_norm, y_norm])
                        
                        lat_pt = math.asin(max(-1.0, min(1.0, pt_body[2])))
                        lon_pt = math.atan2(pt_body[1], pt_body[0])
                        
                        u = (lon_pt + math.pi) / (2 * math.pi)
                        v = (math.pi / 2 - lat_pt) / math.pi
                        
                        tx = int(u * day_w) % day_w
                        ty = int(v * day_h) % day_h
                        r, g, b, _ = earth_day.get_at((tx, ty))
                        
                        cos_sun = np.dot(pt_body / np.linalg.norm(pt_body), sun_earth_dir)
                        if cos_sun > 0.0:
                            if earth_clouds is not None:
                                cx = int(u * clouds_w) % clouds_w
                                cy = int(v * clouds_h) % clouds_h
                                cr, cg, cb, ca = earth_clouds.get_at((cx, cy))
                                cloud_factor = (ca / 255.0) * (cr / 255.0)
                                r = int(r * (1 - cloud_factor * 0.7) + 255 * cloud_factor * 0.7)
                                g = int(g * (1 - cloud_factor * 0.7) + 255 * cloud_factor * 0.7)
                                b = int(b * (1 - cloud_factor * 0.7) + 255 * cloud_factor * 0.7)
                            factor = max(0.15, cos_sun)
                            r, g, b = int(r * factor), int(g * factor), int(b * factor)
                        else:
                            if earth_night is not None:
                                nx = int(u * night_w) % night_w
                                ny = int(v * night_h) % night_h
                                nr, ng, nb, _ = earth_night.get_at((nx, ny))
                                r, g, b = nr, ng, nb
                            else:
                                r, g, b = int(r * 0.05), int(g * 0.05), int(b * 0.05)
                        earth_surf.set_at((px, py), (r, g, b, 255))
                        
                screen.blit(earth_surf, (int(ex) - r_earth, int(ey) - r_earth))
                pygame.draw.circle(screen, (100, 180, 255), (int(ex), int(ey)), r_earth, 2)
            else:
                pygame.draw.circle(screen, (30, 90, 180), (int(ex), int(ey)), r_earth)
                pygame.draw.circle(screen, (120, 190, 255), (int(ex), int(ey)), r_earth, 2)

            pygame.draw.line(screen, (0, 255, 150), (ex - 10, ey), (ex + 10, ey), 1)
            pygame.draw.line(screen, (0, 255, 150), (ex, ey - 10), (ex, ey + 10), 1)
            screen.blit(font.render("Ziemia", True, (130, 200, 255)), (ex + r_earth + 8, ey - 8))

        # Kierunki świata
        for label, deg in [("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315)]:
            proj = project_point(math.radians(1.5), math.radians(deg), cw, ch)
            if proj:
                col = (255, 90, 90) if label == "N" else (180, 180, 190)
                txt = font_big.render(label, True, col)
                screen.blit(txt, (proj[0] - txt.get_width()//2, proj[1] - txt.get_height()//2))

        # HUD
        info_lines = [
            f"Rok: {current_year} | Plik: Coords/{current_year}.csv",
            f"Kamera: Az {math.degrees(cam_az):.1f}° | Alt {math.degrees(cam_alt):+.1f}° | FOV {math.degrees(fov):.1f}°",
            "-" * 45,
            f"ZIEMIA: Alt {math.degrees(earth_alt):+6.2f}° | Az {math.degrees(earth_az):6.2f}°",
            f"SŁOŃCE: Alt {math.degrees(sun_alt):+6.2f}° | Az {math.degrees(sun_az):6.2f}°",
            "EM = Ziemia-Księżyc | SE = Słońce-Ziemia",
            "-" * 45,
            "[Mysz LPM] Rozglądanie | [Scroll] Zoom",
            "[Spacja] Play/Pauza | [E] Ziemia | [S] Słońce"
        ]
        
        panel_w = 510
        panel_surf = pygame.Surface((panel_w, len(info_lines) * 20 + 16), pygame.SRCALPHA)
        panel_surf.fill((15, 20, 30, 190))
        screen.blit(panel_surf, (cw - panel_w - 15, 15))
        
        for i, line in enumerate(info_lines):
            screen.blit(font.render(line, True, (210, 215, 225)), (cw - panel_w - 5, 22 + i * 20))

        slider_year.draw(screen, font)
        slider_time.draw(screen, font, data['time'].strftime('%Y-%m-%d %H:%M UTC'))
        slider_lat.draw(screen, font)
        slider_lon.draw(screen, font)

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
