import csv
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np

from linear_interpolation_position import interpoluj_polozenie

try:
    from time_zone_converter import convert_time_zone, convert_to_utc, define_IANA_zone
except ImportError:
    from time_zone_converter import convert_time_zone, define_IANA_zone

    def convert_to_utc(data_lokalna_str: str, strefa_zrodlowa: str, fold: int = 0) -> str:
        dopasowanie = re.fullmatch(
            r"UTC([+-])(\d{1,2})(?::(\d{2}))?",
            strefa_zrodlowa.strip(),
            re.IGNORECASE,
        )
        if dopasowanie:
            znak, godziny, minuty = dopasowanie.groups()
            przesuniecie = timedelta(hours=int(godziny), minutes=int(minuty or 0))
            if znak == "-":
                przesuniecie = -przesuniecie
            tz = timezone(przesuniecie)
        else:
            tz = ZoneInfo(strefa_zrodlowa)

        dt_lokalny = datetime.strptime(data_lokalna_str.strip(), "%Y-%m-%d %H:%M").replace(
            tzinfo=tz,
            fold=fold,
        )
        return dt_lokalny.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


# ==============================================================================
# KONFIGURACJA PRZEDZIAŁU CZASU (W STREFIE KRAJU/REGIONU) I POŁOŻENIA NA KSIĘŻYCU
# ==============================================================================
DATA_POCZATEK = "2026-12-08 00:00"   # Format: "YYYY-MM-DD HH:MM" (czas lokalny dla KRAJ / REGION)
DATA_KONIEC = "2027-12-08 23:59"     # Format: "YYYY-MM-DD HH:MM" (czas lokalny dla KRAJ / REGION)

KRAJ = "Polska"                      # Nazwa kraju zgodna z time_zone_converter.py
REGION = None                        # Region/stan dla krajów wielostrefowych (np. "Kalifornia"), w przeciwnym razie None

# Współrzędne obserwatora na Księżycu [°]
LAT_DEG = 88.0
LON_DEG = 0.0

FOLDER_DANYCH = "coords"
FOLDER_CACHE_TOPO = "moon_topo_cache"

# --- STAŁE ASTRONOMICZNE ---
R_SUN = 6.96e5                       # Średni promień Słońca [km]
R_MOON = 1737.4                      # Średni promień Księżyca [km]
R_EARTH = 6371.0                     # Średni promień Ziemi [km]
I_MOON = math.radians(1.5424)        # Nachylenie równika księżycowego do ekliptyki
J2000 = datetime(2000, 1, 1, 12, 0, 0)


# ==============================================================================
# TOPOGRAFIA KSIĘŻYCA (LRO LOLA DEM — NASA PDS / USGS ASTROGEOLOGY)
# ==============================================================================
class TopografiaKsiezycaLOLA:
    """
    Pobiera dane wysokościowe LRO LOLA DEM i wyznacza 360-stopniowy profil
    kątowej wysokości gór (horyzontu topograficznego) wokół obserwatora.
    """

    PDS_BASE_URL = (
        "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/"
        "lrolol_1xxx/data/lola_gdr/cylindrical/img"
    )
    USGS_SAMPLES_URL = (
        "https://astrogeology.usgs.gov/arcgis/rest/services/Moon/"
        "LRO_LOLA_DEM_Global_60N60S_512ppd/ImageServer/getSamples"
    )

    def __init__(
        self,
        lat_deg: float,
        lon_deg: float,
        cache_dir: str = FOLDER_CACHE_TOPO,
        max_zasieg_km: float = 220.0,
        liczba_punktow_promienia: int = 160,
        krok_azymutu_deg: float = 1.0,
    ) -> None:
        self.lat_deg = float(lat_deg)
        self.lon_deg = self._normalizuj_lon(float(lon_deg))
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_zasieg_km = max_zasieg_km
        self.liczba_punktow_promienia = liczba_punktow_promienia
        self.krok_azymutu_deg = krok_azymutu_deg

        self.wysokosc_obserwatora_m: float = 0.0
        self.azymuty_deg: np.ndarray = np.arange(0.0, 360.0, krok_azymutu_deg, dtype=np.float64)
        self.katy_horyzontu_rad: np.ndarray = np.zeros_like(self.azymuty_deg)
        self.zrodlo_danych: str = "nieznane"

        self._zaladuj_lub_oblicz_horyzont()

    @staticmethod
    def _normalizuj_lon(lon_deg: float) -> float:
        return ((lon_deg + 180.0) % 360.0) - 180.0

    def _siatka_promieni_sferycznych(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        az_rad = np.radians(self.azymuty_deg)[:, None]
        dystanse_km = np.linspace(0.0, self.max_zasieg_km, self.liczba_punktow_promienia)[None, :]
        delta = dystanse_km / R_MOON

        lat1 = math.radians(self.lat_deg)
        lon1 = math.radians(self.lon_deg)

        sin_lat2 = np.sin(lat1) * np.cos(delta) + np.cos(lat1) * np.sin(delta) * np.cos(az_rad)
        sin_lat2 = np.clip(sin_lat2, -1.0, 1.0)
        lat2 = np.arcsin(sin_lat2)

        lon2 = lon1 + np.arctan2(
            np.sin(az_rad) * np.sin(delta) * np.cos(lat1),
            np.cos(delta) - np.sin(lat1) * sin_lat2,
        )
        lat2_deg = np.degrees(lat2)
        lon2_deg = ((np.degrees(lon2) + 180.0) % 360.0) - 180.0
        return lat2_deg, lon2_deg, dystanse_km[0]

    def _oblicz_horyzont_z_profili(
        self,
        wysokosci_m: np.ndarray,
        dystanse_km: np.ndarray,
    ) -> tuple[float, np.ndarray]:
        wys_obs_m = float(np.median(wysokosci_m[:, 0]))
        r0 = R_MOON + (wys_obs_m / 1000.0)

        rk = R_MOON + (wysokosci_m[:, 1:] / 1000.0)
        delta = (dystanse_km[1:] / R_MOON)[None, :]

        dy = rk * np.cos(delta) - r0
        dx = rk * np.sin(delta)
        katy_rad = np.arctan2(dy, dx)
        katy_max_rad = np.max(katy_rad, axis=1)
        return wys_obs_m, katy_max_rad

    @staticmethod
    def _interpoluj_z_wycinka_dem(
        siatka_m: np.ndarray,
        row_start: int,
        ppd: int,
        lat_deg_grid: np.ndarray,
        lon_deg_grid: np.ndarray,
    ) -> np.ndarray:
        n_rows_sub, n_cols = siatka_m.shape
        r_f = (90.0 - lat_deg_grid) * ppd - 0.5 - row_start
        c_f = (lon_deg_grid % 360.0) * ppd - 0.5

        r0 = np.clip(np.floor(r_f).astype(np.int64), 0, n_rows_sub - 1)
        r1 = np.clip(r0 + 1, 0, n_rows_sub - 1)
        wr = np.clip(r_f - r0, 0.0, 1.0)

        c0 = np.floor(c_f).astype(np.int64) % n_cols
        c1 = (c0 + 1) % n_cols
        wc = c_f - np.floor(c_f)

        v00 = siatka_m[r0, c0]
        v01 = siatka_m[r0, c1]
        v10 = siatka_m[r1, c0]
        v11 = siatka_m[r1, c1]

        return (
            (1.0 - wr) * ((1.0 - wc) * v00 + wc * v01)
            + wr * ((1.0 - wc) * v10 + wc * v11)
        )

    def _pobierz_z_nasa_pds_range(
        self,
        lat_grid: np.ndarray,
        lon_grid: np.ndarray,
        dystanse_km: np.ndarray,
        ppd: int = 64,
    ) -> tuple[float, np.ndarray, str]:
        n_rows = 180 * ppd
        n_cols = 360 * ppd
        bytes_per_row = n_cols * 2

        lat_min = float(np.min(lat_grid))
        lat_max = float(np.max(lat_grid))

        row_start = max(0, int(math.floor((90.0 - lat_max) * ppd)) - 2)
        row_end = min(n_rows - 1, int(math.ceil((90.0 - lat_min) * ppd)) + 2)

        byte_start = row_start * bytes_per_row
        byte_end = (row_end + 1) * bytes_per_row - 1

        url = f"{self.PDS_BASE_URL}/ldem_{ppd}.img"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "LunarElevationModel/1.0",
                "Range": f"bytes={byte_start}-{byte_end}",
            },
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            if resp.status not in (200, 206):
                raise RuntimeError(f"Nieoczekiwany status HTTP: {resp.status}")
            buf = resp.read()

        expected_bytes = (row_end - row_start + 1) * bytes_per_row
        if resp.status == 200 and len(buf) == n_rows * bytes_per_row:
            row_start = 0
            row_end = n_rows - 1
            expected_bytes = len(buf)

        if len(buf) < expected_bytes:
            raise ValueError(f"Niekompletna odpowiedź z NASA PDS ({len(buf)} / {expected_bytes} B).")

        siatka_raw = np.frombuffer(buf[:expected_bytes], dtype="<i2").reshape(
            (row_end - row_start + 1, n_cols)
        )
        siatka_m = siatka_raw.astype(np.float64) * 0.5
        wys_m = self._interpoluj_z_wycinka_dem(siatka_m, row_start, ppd, lat_grid, lon_grid)
        wys_obs_m, katy_rad = self._oblicz_horyzont_z_profili(wys_m, dystanse_km)
        return wys_obs_m, katy_rad, f"NASA PDS LRO LOLA GDR (ldem_{ppd}.img, {ppd} ppd)"

    def _pobierz_z_nasa_pds_pelny_plik(
        self,
        lat_grid: np.ndarray,
        lon_grid: np.ndarray,
        dystanse_km: np.ndarray,
        ppd: int = 16,
    ) -> tuple[float, np.ndarray, str]:
        n_rows = 180 * ppd
        n_cols = 360 * ppd
        lokalny_img = self.cache_dir / f"ldem_{ppd}.img"

        if not lokalny_img.exists():
            url = f"{self.PDS_BASE_URL}/ldem_{ppd}.img"
            req = urllib.request.Request(url, headers={"User-Agent": "LunarElevationModel/1.0"})
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                dane = resp.read()
            if len(dane) != n_rows * n_cols * 2:
                raise ValueError(f"Nieprawidłowy rozmiar pliku ldem_{ppd}.img: {len(dane)} B")
            lokalny_img.write_bytes(dane)

        siatka_raw = np.fromfile(lokalny_img, dtype="<i2").reshape((n_rows, n_cols))
        siatka_m = siatka_raw.astype(np.float64) * 0.5
        wys_m = self._interpoluj_z_wycinka_dem(siatka_m, 0, ppd, lat_grid, lon_grid)
        wys_obs_m, katy_rad = self._oblicz_horyzont_z_profili(wys_m, dystanse_km)
        return wys_obs_m, katy_rad, f"NASA PDS LRO LOLA GDR (ldem_{ppd}.img, {ppd} ppd)"

    def _pobierz_z_usgs_astrogeology(
        self,
        lat_grid: np.ndarray,
        lon_grid: np.ndarray,
        dystanse_km: np.ndarray,
    ) -> tuple[float, np.ndarray, str]:
        n_az, n_d = lat_grid.shape
        punkty_flat = [
            [round(float(lon), 5), round(float(lat), 5)]
            for lat, lon in zip(lat_grid.ravel(), lon_grid.ravel())
        ]
        wysokosci_flat: list[float] = []
        rozmiar_paczki = 500

        for i in range(0, len(punkty_flat), rozmiar_paczki):
            paczka = punkty_flat[i : i + rozmiar_paczki]
            geometry = json.dumps({"points": paczka, "spatialReference": {"wkid": 4326}})
            body = urllib.parse.urlencode(
                {
                    "geometry": geometry,
                    "geometryType": "esriGeometryMultipoint",
                    "returnFirstValueOnly": "true",
                    "f": "json",
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                self.USGS_SAMPLES_URL,
                data=body,
                headers={"User-Agent": "LunarElevationModel/1.0"},
            )
            with urllib.request.urlopen(req, timeout=25.0) as resp:
                wynik = json.loads(resp.read().decode("utf-8"))
            samples = wynik.get("samples", [])
            if len(samples) != len(paczka):
                raise ValueError("Niekompletna lista próbek z USGS Astrogeology.")
            for s in samples:
                wysokosci_flat.append(float(s["value"]))

        wys_m = np.array(wysokosci_flat, dtype=np.float64).reshape((n_az, n_d))
        wys_obs_m, katy_rad = self._oblicz_horyzont_z_profili(wys_m, dystanse_km)
        return wys_obs_m, katy_rad, "USGS Astrogeology LRO LOLA DEM"

    def _zaladuj_lub_oblicz_horyzont(self) -> None:
        plik_cache = self.cache_dir / f"horyzont_lat_{self.lat_deg:+.4f}_lon_{self.lon_deg:+.4f}.json"
        if plik_cache.exists():
            with open(plik_cache, mode="r", encoding="utf-8") as f:
                dane_cache = json.load(f)
            self.wysokosc_obserwatora_m = float(dane_cache["wysokosc_obserwatora_m"])
            self.azymuty_deg = np.array(dane_cache["azymuty_deg"], dtype=np.float64)
            self.katy_horyzontu_rad = np.array(dane_cache["katy_horyzontu_rad"], dtype=np.float64)
            self.zrodlo_danych = dane_cache.get("zrodlo_danych", "LOLA DEM cache")
            return

        lat_grid, lon_grid, dystanse_km = self._siatka_promieni_sferycznych()
        bledy: list[str] = []

        metody = (
            lambda: self._pobierz_z_nasa_pds_range(lat_grid, lon_grid, dystanse_km, ppd=64),
            lambda: self._pobierz_z_nasa_pds_pelny_plik(lat_grid, lon_grid, dystanse_km, ppd=16),
            lambda: self._pobierz_z_usgs_astrogeology(lat_grid, lon_grid, dystanse_km),
        )

        for metoda in metody:
            try:
                wys_obs_m, katy_rad, zrodlo = metoda()
                self.wysokosc_obserwatora_m = wys_obs_m
                self.katy_horyzontu_rad = katy_rad
                self.zrodlo_danych = zrodlo

                with open(plik_cache, mode="w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "lat_deg": self.lat_deg,
                            "lon_deg": self.lon_deg,
                            "wysokosc_obserwatora_m": self.wysokosc_obserwatora_m,
                            "azymuty_deg": self.azymuty_deg.tolist(),
                            "katy_horyzontu_rad": self.katy_horyzontu_rad.tolist(),
                            "zrodlo_danych": self.zrodlo_danych,
                        },
                        f,
                        indent=2,
                    )
                print(f"[INFO] Załadowano topografię Księżyca ze źródła: {self.zrodlo_danych}")
                return
            except Exception as exc:
                bledy.append(str(exc))

        self.wysokosc_obserwatora_m = 0.0
        self.katy_horyzontu_rad = np.zeros_like(self.azymuty_deg)
        self.zrodlo_danych = "Fallback sferyczny (brak dostępu do sieci)"
        print(f"[UWAGA] Nie udało się pobrać danych LOLA DEM ({'; '.join(bledy)}). Użyto modelu sferycznego.")

    def kat_horyzontu(self, azymut_rad: float) -> float:
        """Interpoluje liniowo kąt horyzontu topograficznego [rad] dla dowolnego azymutu [rad]."""
        az_deg = math.degrees(azymut_rad) % 360.0
        az_ext = np.append(self.azymuty_deg, 360.0)
        katy_ext = np.append(self.katy_horyzontu_rad, self.katy_horyzontu_rad[0])
        return float(np.interp(az_deg, az_ext, katy_ext))


# ==============================================================================
# MECHANIKA NIEBA I GEOMETRIA WIDOCZNOŚCI SŁOŃCA, ZIEMI ORAZ GÓR
# ==============================================================================
def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=np.float64)


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def _macierz_orientacji_ksiezyca(d_j2000: float) -> np.ndarray:
    """Macierz transformacji z układu ekliptycznego do układu związanego z bryłą Księżyca."""
    omega = math.radians(125.04452 - 0.0529537648 * d_j2000)
    L = math.radians(218.3164477 + 13.17639648 * d_j2000)
    node_eq = omega + math.pi
    W = L - node_eq + math.pi
    return _rot_z(-W) @ _rot_x(-I_MOON) @ _rot_z(-node_eq)


def oblicz_katy_elewacji_i_gor(
    dt_utc: datetime,
    wiersz_6: list[float],
    lat_deg: float,
    lon_deg: float,
    topografia: TopografiaKsiezycaLOLA,
) -> tuple[float, float, float, float]:
    """
    Oblicza dla obserwatora na powierzchni Księżyca (lat_deg, lon_deg):
      1) elewacja_gornej_krawedzi_slonca_deg: kąt elewacji górnej krawędzi tarczy Słońca [°]
         od matematycznego horyzontu,
      2) elewacja_dolnej_krawedzi_ziemi_deg: kąt elewacji dolnej krawędzi tarczy Ziemi [°]
         od matematycznego horyzontu,
      3) wysokosc_gor_slonce_deg: wysokość kątowa gór [°] w azymucie Słońca,
      4) wysokosc_gor_ziemia_deg: wysokość kątowa gór [°] w azymucie Ziemi.
    """
    vec = np.array(wiersz_6, dtype=np.float64)
    if np.linalg.norm(vec[3:6]) > 1e7:
        vec *= 0.001

    sun_geo = vec[0:3]
    moon_geo = vec[3:6]

    sun_seleno_ecl = sun_geo - moon_geo
    earth_seleno_ecl = -moon_geo

    d_j2000 = (dt_utc - J2000).total_seconds() / 86400.0
    R_body = _macierz_orientacji_ksiezyca(d_j2000)

    sun_body = R_body @ sun_seleno_ecl
    earth_body = R_body @ earth_seleno_ecl

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    up = np.array(
        [
            math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon),
            math.sin(lat),
        ],
        dtype=np.float64,
    )
    east = np.array([-math.sin(lon), math.cos(lon), 0.0], dtype=np.float64)
    north = np.array(
        [
            -math.sin(lat) * math.cos(lon),
            -math.sin(lat) * math.sin(lon),
            math.cos(lat),
        ],
        dtype=np.float64,
    )

    r_obs = R_MOON + (topografia.wysokosc_obserwatora_m / 1000.0)
    obs_body = r_obs * up

    # 1. Kąt elewacji górnej części tarczy Słońca oraz azymut Słońca
    vec_sun = sun_body - obs_body
    dist_sun = float(np.linalg.norm(vec_sun))
    sin_alt_sun_center = max(-1.0, min(1.0, float(np.dot(vec_sun, up)) / dist_sun))
    alt_sun_center_rad = math.asin(sin_alt_sun_center)
    promien_katowy_slonca_rad = math.asin(min(1.0, R_SUN / dist_sun))
    elewacja_gornej_krawedzi_slonca_deg = math.degrees(
        alt_sun_center_rad + promien_katowy_slonca_rad
    )

    azymut_slonca_rad = math.atan2(
        float(np.dot(vec_sun, east)),
        float(np.dot(vec_sun, north)),
    ) % (2.0 * math.pi)
    wysokosc_gor_slonce_deg = math.degrees(topografia.kat_horyzontu(azymut_slonca_rad))

    # 2. Kąt elewacji dolnej części tarczy Ziemi oraz azymut Ziemi
    vec_earth = earth_body - obs_body
    dist_earth = float(np.linalg.norm(vec_earth))
    sin_alt_earth_center = max(-1.0, min(1.0, float(np.dot(vec_earth, up)) / dist_earth))
    alt_earth_center_rad = math.asin(sin_alt_earth_center)
    promien_katowy_ziemi_rad = math.asin(min(1.0, R_EARTH / dist_earth))
    elewacja_dolnej_krawedzi_ziemi_deg = math.degrees(
        alt_earth_center_rad - promien_katowy_ziemi_rad
    )

    azymut_ziemi_rad = math.atan2(
        float(np.dot(vec_earth, east)),
        float(np.dot(vec_earth, north)),
    ) % (2.0 * math.pi)
    wysokosc_gor_ziemia_deg = math.degrees(topografia.kat_horyzontu(azymut_ziemi_rad))

    return (
        elewacja_gornej_krawedzi_slonca_deg,
        elewacja_dolnej_krawedzi_ziemi_deg,
        wysokosc_gor_slonce_deg,
        wysokosc_gor_ziemia_deg,
    )


def generuj_punkty_czasowe(data_poczatek_utc: str, data_koniec_utc: str) -> list[datetime]:
    """
    Tworzy listę znaczników czasu (UTC): początek przedziału, wszystkie pełne godziny
    wewnątrz przedziału oraz koniec przedziału.
    """
    t_start = datetime.strptime(data_poczatek_utc.strip(), "%Y-%m-%d %H:%M")
    t_end = datetime.strptime(data_koniec_utc.strip(), "%Y-%m-%d %H:%M")

    if t_end < t_start:
        raise ValueError("DATA_KONIEC nie może być wcześniejsza niż DATA_POCZATEK.")

    if t_start == t_end:
        return [t_start]

    punkty = [t_start]
    cur = t_start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while cur < t_end:
        punkty.append(cur)
        cur += timedelta(hours=1)

    if punkty[-1] != t_end:
        punkty.append(t_end)

    return punkty


def _oblicz_dane_elewacji(
    data_poczatek_lokalna: str,
    data_koniec_lokalna: str,
    kraj: str = KRAJ,
    region: str | None = REGION,
    lat_deg: float = LAT_DEG,
    lon_deg: float = LON_DEG,
    folder: str = FOLDER_DANYCH,
    folder_cache_topo: str = FOLDER_CACHE_TOPO,
) -> tuple[list[list], list[float]]:
    """
    Zwraca:
      1) 4-kolumnową tabelę `tablica`:
         [
           data i godzina,
           wysokość górnej części Słońca nad horyzontem [°],
           wysokość dolnej części tarczy Ziemi nad horyzontem [°],
           wysokość kątowa gór (w azymucie Słońca) [°],
         ]
      2) listę `wysokosci_gor_ziemia` [°] (wysokość kątowa gór w azymucie Ziemi) do wykresu 2.
    """
    strefa_iana = define_IANA_zone(kraj, region)
    if strefa_iana.startswith("Błąd"):
        raise ValueError(f"{strefa_iana} dla kraju '{kraj}'.")

    data_poczatek_utc = convert_to_utc(data_poczatek_lokalna, strefa_iana)
    data_koniec_utc = convert_to_utc(data_koniec_lokalna, strefa_iana)

    punkty_czasu_utc = generuj_punkty_czasowe(data_poczatek_utc, data_koniec_utc)

    topografia = TopografiaKsiezycaLOLA(
        lat_deg=lat_deg,
        lon_deg=lon_deg,
        cache_dir=folder_cache_topo,
    )

    lata_pelnych_godzin = sorted(
        {dt.year for dt in punkty_czasu_utc if dt.minute == 0 and dt.second == 0}
    )
    dane_godzinowe: dict[str, list[float]] = {}

    for rok in lata_pelnych_godzin:
        sciezka = Path(folder) / f"{rok}.csv"
        if not sciezka.exists():
            raise FileNotFoundError(f"Brak pliku z danymi: {sciezka}")
        with open(sciezka, mode="r", encoding="utf-8", newline="") as plik:
            reader = csv.reader(plik)
            next(reader)
            for wiersz in reader:
                dane_godzinowe[wiersz[0]] = [float(x) for x in wiersz[1:7]]

    tablica: list[list] = []
    wysokosci_gor_ziemia: list[float] = []

    for dt_utc in punkty_czasu_utc:
        if dt_utc.minute == 0 and dt_utc.second == 0:
            klucz = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
            if klucz not in dane_godzinowe:
                raise ValueError(f"Nie znaleziono rekordu {klucz} w folderze '{folder}'.")
            wiersz_6 = dane_godzinowe[klucz]
        else:
            interp = interpoluj_polozenie(dt_utc.strftime("%Y-%m-%d %H:%M"), folder=folder)
            wiersz_6 = [float(x) for x in interp[1:7]]

        (
            kat_slonce_gora,
            kat_ziemia_dol,
            kat_gory_slonce,
            kat_gory_ziemia,
        ) = oblicz_katy_elewacji_i_gor(dt_utc, wiersz_6, lat_deg, lon_deg, topografia)

        czas_lokalny_str = convert_time_zone(dt_utc.strftime("%Y-%m-%d %H:%M"), strefa_iana)
        tablica.append([czas_lokalny_str, kat_slonce_gora, kat_ziemia_dol, kat_gory_slonce])
        wysokosci_gor_ziemia.append(kat_gory_ziemia)

    return tablica, wysokosci_gor_ziemia


def generuj_tablice_elewacji(
    data_poczatek_lokalna: str,
    data_koniec_lokalna: str,
    kraj: str = KRAJ,
    region: str | None = REGION,
    lat_deg: float = LAT_DEG,
    lon_deg: float = LON_DEG,
    folder: str = FOLDER_DANYCH,
    folder_cache_topo: str = FOLDER_CACHE_TOPO,
) -> list[list]:
    """
    Zwraca 4-kolumnową tabelę `tablica_elewacji`:
      1. data i godzina (czas lokalny 'YYYY-MM-DD HH:MM')
      2. wysokość górnej części Słońca nad horyzontem matematycznym [°]
      3. wysokość dolnej części tarczy Ziemi nad horyzontem matematycznym [°]
      4. wysokość kątowa gór [°]
    """
    tablica, _ = _oblicz_dane_elewacji(
        data_poczatek_lokalna=data_poczatek_lokalna,
        data_koniec_lokalna=data_koniec_lokalna,
        kraj=kraj,
        region=region,
        lat_deg=lat_deg,
        lon_deg=lon_deg,
        folder=folder,
        folder_cache_topo=folder_cache_topo,
    )
    return tablica


def _formatuj_offset_utc(offset: timedelta | None) -> str:
    """Formatuje przesunięcie względem UTC do postaci np. 'UTC+11.30' lub 'UTC-9'."""
    if offset is None:
        return "UTC"
    total_seconds = int(offset.total_seconds())
    znak = "+" if total_seconds >= 0 else "-"
    abs_seconds = abs(total_seconds)
    godziny, reszta = divmod(abs_seconds, 3600)
    minuty = reszta // 60
    if minuty:
        return f"UTC{znak}{godziny}.{minuty:02d}"
    return f"UTC{znak}{godziny}"


def _formatuj_strefe_utc(strefa_iana: str, daty: list[datetime]) -> str:
    """Zwraca etykietę strefy czasowej w formacie 'UTC+11.30' / 'UTC-9' dla podanych dat."""
    dopasowanie = re.fullmatch(
        r"UTC([+-])(\d{1,2})(?:[:.](\d{2}))?",
        strefa_iana.strip(),
        re.IGNORECASE,
    )
    if dopasowanie:
        znak, godziny, minuty = dopasowanie.groups()
        przesuniecie = timedelta(hours=int(godziny), minutes=int(minuty or 0))
        if znak == "-":
            przesuniecie = -przesuniecie
        tz = timezone(przesuniecie)
    else:
        tz = ZoneInfo(strefa_iana)

    if not daty:
        return _formatuj_offset_utc(datetime.now(tz).utcoffset())

    offset_start = daty[0].replace(tzinfo=tz).utcoffset()
    offset_end = daty[-1].replace(tzinfo=tz).utcoffset()
    utc_start = _formatuj_offset_utc(offset_start)
    utc_end = _formatuj_offset_utc(offset_end)

    if utc_start == utc_end:
        return utc_start
    return f"{utc_start}/{utc_end}"


def rysuj_wykresy_elewacji(
    tablica_elewacji: list[list],
    lat_deg: float,
    lon_deg: float,
    strefa_iana: str,
    wysokosci_gor_ziemia: list[float] | None = None,
) -> None:
    """
    Wizualizuje 2 wykresy w matplotlib:
      1) wysokość górnej części tarczy Słońca od czasu i jednocześnie wysokość kątową gór,
      2) wysokość dolnej części tarczy Ziemi od czasu i jednocześnie wysokość kątową gór.
    """
    daty = [datetime.strptime(wiersz[0], "%Y-%m-%d %H:%M") for wiersz in tablica_elewacji]
    elewacje_slonca_gora = [wiersz[1] for wiersz in tablica_elewacji]
    elewacje_ziemi_dol = [wiersz[2] for wiersz in tablica_elewacji]
    wysokosci_gor_slonce = [wiersz[3] for wiersz in tablica_elewacji]
    gory_do_ziemi = (
        wysokosci_gor_ziemia if wysokosci_gor_ziemia is not None else wysokosci_gor_slonce
    )
    strefa_utc = _formatuj_strefe_utc(strefa_iana, daty)

    # --- Wykres 1: Górna część tarczy Słońca oraz wysokość kątowa gór ---
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(
        daty,
        elewacje_slonca_gora,
        color="#f59e0b",
        linewidth=1.8,
        label="Wysokość górnej części tarczy Słońca [°]",
    )
    ax1.plot(
        daty,
        wysokosci_gor_slonce,
        color="#475569",
        linewidth=1.8,
        label="Wysokość kątowa gór (azymut Słońca) [°]",
    )
    ax1.axhline(
        0.0,
        color="#0284c7",
        linestyle="--",
        linewidth=1.2,
        label="Horyzont matematyczny (0°)",
    )

    ax1.fill_between(
        daty,
        elewacje_slonca_gora,
        wysokosci_gor_slonce,
        where=[s > g for s, g in zip(elewacje_slonca_gora, wysokosci_gor_slonce)],
        color="#fde047",
        alpha=0.25,
        interpolate=True,
        label="Górna część tarczy Słońca ponad górami",
    )

    if len(daty) > 1:
        ax1.set_xlim(daty[0], daty[-1])

    ax1.set_title(
        f"Wysokość górnej części tarczy Słońca oraz wysokość kątowa gór na Księżycu "
        f"(Lat: {lat_deg:+.2f}°, Lon: {lon_deg:+.2f}° | {strefa_utc})"
    )
    ax1.set_xlabel(f"Data i godzina ({strefa_utc})")
    ax1.set_ylabel("Wysokość kątowa [°]")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="best")
    fig1.autofmt_xdate()
    fig1.tight_layout()

    # --- Wykres 2: Dolna część tarczy Ziemi oraz wysokość kątowa gór ---
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    ax2.plot(
        daty,
        elewacje_ziemi_dol,
        color="#2563eb",
        linewidth=1.8,
        label="Wysokość dolnej części tarczy Ziemi [°]",
    )
    ax2.plot(
        daty,
        gory_do_ziemi,
        color="#475569",
        linewidth=1.8,
        label="Wysokość kątowa gór (azymut Ziemi) [°]",
    )
    ax2.axhline(
        0.0,
        color="#0284c7",
        linestyle="--",
        linewidth=1.2,
        label="Horyzont matematyczny (0°)",
    )

    ax2.fill_between(
        daty,
        elewacje_ziemi_dol,
        gory_do_ziemi,
        where=[z > g for z, g in zip(elewacje_ziemi_dol, gory_do_ziemi)],
        color="#38bdf8",
        alpha=0.25,
        interpolate=True,
        label="Cała tarcza Ziemi ponad górami",
    )

    if len(daty) > 1:
        ax2.set_xlim(daty[0], daty[-1])

    ax2.set_title(
        f"Wysokość dolnej części tarczy Ziemi (R = 6371 km) oraz wysokość kątowa gór na Księżycu "
        f"(Lat: {lat_deg:+.2f}°, Lon: {lon_deg:+.2f}° | {strefa_utc})"
    )
    ax2.set_xlabel(f"Data i godzina ({strefa_utc})")
    ax2.set_ylabel("Wysokość kątowa [°]")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="best")
    fig2.autofmt_xdate()
    fig2.tight_layout()

    plt.show()


if __name__ == "__main__":
    strefa = define_IANA_zone(KRAJ, REGION)
    tablica_elewacji, wysokosci_gor_ziemia = _oblicz_dane_elewacji(
        DATA_POCZATEK,
        DATA_KONIEC,
        kraj=KRAJ,
        region=REGION,
        lat_deg=LAT_DEG,
        lon_deg=LON_DEG,
        folder=FOLDER_DANYCH,
        folder_cache_topo=FOLDER_CACHE_TOPO,
    )
    '''
    print(f"Liczba wierszy w tablica_elewacji: {len(tablica_elewacji)} (kolumny: {len(tablica_elewacji[0])})")
    for wiersz in tablica_elewacji[:10]:
        print(
            f"{wiersz[0]} | "
            f"Słońce (góra) = {wiersz[1]:+6.2f}° | "
            f"Ziemia (dół) = {wiersz[2]:+6.2f}° | "
            f"Góry = {wiersz[3]:+6.2f}°"
        )

    rysuj_wykresy_elewacji(
        tablica_elewacji,
        LAT_DEG,
        LON_DEG,
        strefa,
        wysokosci_gor_ziemia=wysokosci_gor_ziemia,
    )'''
