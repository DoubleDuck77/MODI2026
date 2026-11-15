import csv
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


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
# KONFIGURACJA PRZEDZIAŁU CZASU, STREFY CZASOWEJ I WSPÓŁRZĘDNYCH SELENOGRAFICZNYCH
# ==============================================================================
DATA_POCZATEK = "2026-12-07 02:00"   # Format: "YYYY-MM-DD HH:MM" (czas lokalny dla KRAJ / REGION)
DATA_KONIEC = "2027-01-15 23:00"     # Format: "YYYY-MM-DD HH:MM" (czas lokalny dla KRAJ / REGION)

KRAJ = "Poland"                      # Nazwa kraju zgodna z time_zone_converter.py
REGION = None                        # Region/stan dla krajów wielostrefowych (np. "Kalifornia"), inaczej None

# Współrzędne selenograficzne obserwatora na Księżycu [°]
LAT_DEG = -87                        # Szerokość selenograficzna [-90, +90] (np. okolice krateru Tycho)
LON_DEG = 10                         # Długość selenograficzna [-180, +180]

FOLDER_DANYCH = "coords"
FOLDER_CACHE_TOPO = "moon_topo_cache"

# --- STAŁE FIZYCZNE I ASTRONOMICZNE ---
I_S = 1361.0                         # Stała słoneczna [W/m^2]
R_SUN = 6.96e5                       # Promień Słońca [km]
R_MOON = 1737.4                      # Średni promień Księżyca [km]
I_MOON = math.radians(1.5424)        # Nachylenie równika księżycowego do ekliptyki
J2000 = datetime(2000, 1, 1, 12, 0, 0)


# ==============================================================================
# POBIERANIE DANYCH TOPOGRAFICZNYCH LRO LOLA DEM (NASA PDS / USGS ASTROGEOLOGY)
# ==============================================================================
class TopografiaKsiezycaLOLA:
    """
    Pobiera dane wysokościowe LRO LOLA DEM (te same, z których korzysta Moon Trek)
    z oficjalnego archiwum NASA PDS Geosciences Node (ldem_64.img / ldem_16.img)
    lub z serwisu USGS Astrogeology i wyznacza 360-stopniowy profil horyzontu.
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
        """
        Wyznacza macierze współrzędnych (lat_deg, lon_deg) dla wszystkich azymutów
        oraz dystansów od 0 do max_zasieg_km wzdłuż ortodrom na sferze Księżyca.
        """
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
        """
        Dla macierzy wysokości (N_az, N_d) [m] oblicza wysokość obserwatora
        oraz maksymalny kąt elewacji terenu [rad] w każdym z 360 azymutów,
        uwzględniając krzywiznę Księżyca.
        """
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
        """Dwuliniowa interpolacja wysokości [m] z wycinka pasma szerokościowego LOLA GDR."""
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
        """
        Pobiera z NASA PDS Geosciences Node wyłącznie pasmo wierszy pliku ldem_64.img
        (rozdzielczość ~473 m/px) obejmujące otoczenie obserwatora za pomocą HTTP Range.
        """
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
                "User-Agent": "LunarSolarIrradianceModel/1.0",
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
        """
        Pobiera globalny plik ldem_16.img (~33 MB, ~1.89 km/px) z NASA PDS i zapisuje go lokalnie,
        aby kolejne obliczenia dla dowolnych współrzędnych działały natychmiast offline.
        """
        n_rows = 180 * ppd
        n_cols = 360 * ppd
        lokalny_img = self.cache_dir / f"ldem_{ppd}.img"

        if not lokalny_img.exists():
            url = f"{self.PDS_BASE_URL}/ldem_{ppd}.img"
            req = urllib.request.Request(url, headers={"User-Agent": "LunarSolarIrradianceModel/1.0"})
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
        """Zapasowe źródło: USGS Astrogeology LRO LOLA ImageServer REST API."""
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
                headers={"User-Agent": "LunarSolarIrradianceModel/1.0"},
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
# MECHANIKA NIEBA I GEOMETRIA WIDOCZNOŚCI TARCZY SŁOŃCA
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


def oblicz_pozycje_slonca_na_niebie_ksiezyca(
    dt_utc: datetime,
    wiersz_6: list[float],
    lat_deg: float,
    lon_deg: float,
    wysokosc_obs_m: float = 0.0,
) -> tuple[float, float, float]:
    """
    Zwraca krotkę (z_rad, azymut_rad, dystans_slonce_km):
      - z_rad: kąt elewacji środka Słońca od lokalnego horyzontu matematycznego [rad],
      - azymut_rad: azymut środka Słońca mierzony od północy na wschód [rad],
      - dystans_slonce_km: odległość od obserwatora na Księżycu do środka Słońca [km].
    """
    vec = np.array(wiersz_6, dtype=np.float64)
    sun_geo = vec[0:3]   # [km]
    moon_geo = vec[3:6]  # [km]

    sun_seleno_ecl = sun_geo - moon_geo
    d_j2000 = (dt_utc - J2000).total_seconds() / 86400.0
    R_body = _macierz_orientacji_ksiezyca(d_j2000)
    sun_body = R_body @ sun_seleno_ecl

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    up = np.array(
        [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)],
        dtype=np.float64,
    )
    east = np.array([-math.sin(lon), math.cos(lon), 0.0], dtype=np.float64)
    north = np.array(
        [-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)],
        dtype=np.float64,
    )

    r_obs = R_MOON + (wysokosc_obs_m / 1000.0)
    obs_body = r_obs * up

    vec_sun = sun_body - obs_body
    dystans_slonce_km = float(np.linalg.norm(vec_sun))

    v_e = float(np.dot(vec_sun, east))
    v_n = float(np.dot(vec_sun, north))
    v_u = float(np.dot(vec_sun, up))

    sin_z = max(-1.0, min(1.0, v_u / dystans_slonce_km))
    z_rad = math.asin(sin_z)
    azymut_rad = math.atan2(v_e, v_n) % (2.0 * math.pi)

    return z_rad, azymut_rad, dystans_slonce_km


def oblicz_widoczny_ulamek_tarczy_slonca(
    z_rad: float,
    azymut_rad: float,
    dystans_slonce_km: float,
    topografia: TopografiaKsiezycaLOLA,
    liczba_paskow: int = 31,
) -> float:
    """
    Dzieli okrągłą tarczę Słońca na `liczba_paskow` PIONOWYCH pasów wzdłuż osi azymutu.
    Dla każdego pasa pionowego oblicza, jaki procent tego pasa jest widoczny ponad
    lokalnym horyzontem topograficznym, waży ten procent udziałem powierzchni danego
    pasa w całkowitej powierzchni tarczy Słońca i sumuje wyniki (zwracając alpha w [0.0, 1.0]).
    """
    rho_sun = math.asin(min(1.0, R_SUN / dystans_slonce_km))
    cos_z = max(1e-4, math.cos(z_rad))

    # Podział szerokości kątowej tarczy Słońca [-rho_sun, +rho_sun] na pionowe pasy
    krawedzie_x = np.linspace(-rho_sun, rho_sun, liczba_paskow + 1)
    srodki_x = 0.5 * (krawedzie_x[:-1] + krawedzie_x[1:])
    szerokosc_pasa_dx = float(krawedzie_x[1] - krawedzie_x[0])

    # Całkowita wysokość, pole i procent widoczności dla każdego pasa pionowego
    wysokosci_paskow: list[float] = []
    pola_paskow: list[float] = []
    procenty_widoczne_paskow: list[float] = []

    for x in srodki_x:
        polowa_cieciwy = math.sqrt(max(0.0, rho_sun ** 2 - float(x) ** 2))
        z_dol = z_rad - polowa_cieciwy
        z_gora = z_rad + polowa_cieciwy
        calkowita_wysokosc_pasa = z_gora - z_dol

        if calkowita_wysokosc_pasa <= 0.0:
            continue

        az_paska = (azymut_rad + float(x) / cos_z) % (2.0 * math.pi)
        h_horyzontu = topografia.kat_horyzontu(az_paska)

        widoczna_wysokosc_pasa = max(0.0, z_gora - max(z_dol, h_horyzontu))
        procent_widoczny_pasa = (widoczna_wysokosc_pasa / calkowita_wysokosc_pasa) * 100.0

        wysokosci_paskow.append(calkowita_wysokosc_pasa)
        pola_paskow.append(calkowita_wysokosc_pasa * szerokosc_pasa_dx)
        procenty_widoczne_paskow.append(procent_widoczny_pasa)

    pole_calkowite_paskow = sum(pola_paskow)
    if pole_calkowite_paskow <= 0.0:
        return 0.0

    # Suma procentów widoczności wszystkich pionowych pasów ważona ich udziałem w polu tarczy
    suma_procentow_tarczy = sum(
        procent_pasa * (pole_pasa / pole_calkowite_paskow)
        for procent_pasa, pole_pasa in zip(procenty_widoczne_paskow, pola_paskow)
    )

    alpha = suma_procentow_tarczy / 100.0
    return max(0.0, min(1.0, alpha))


# ==============================================================================
# GENEROWANIE TABELI NASŁONECZNIENIA I ENERGII SKUMULOWANEJ
# ==============================================================================
def generuj_punkty_czasowe(
    data_poczatek_utc: str,
    data_koniec_utc: str,
    krok_minut: int = 60,
) -> list[datetime]:
    """
    Tworzy chronologiczną listę znaczników czasu (UTC) od początku do końca przedziału.
    """
    t_start = datetime.strptime(data_poczatek_utc.strip(), "%Y-%m-%d %H:%M")
    t_end = datetime.strptime(data_koniec_utc.strip(), "%Y-%m-%d %H:%M")

    if t_end < t_start:
        raise ValueError("DATA_KONIEC nie może być wcześniejsza niż DATA_POCZATEK.")
    if t_start == t_end:
        return [t_start]

    punkty = [t_start]
    if krok_minut == 60:
        cur = t_start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        cur = t_start + timedelta(minutes=krok_minut)

    while cur < t_end:
        punkty.append(cur)
        cur += timedelta(minutes=krok_minut)

    if punkty[-1] != t_end:
        punkty.append(t_end)

    return punkty


def generuj_dane_naslonecznienia(
    data_poczatek_lokalna: str,
    data_koniec_lokalna: str,
    kraj: str = KRAJ,
    region: str | None = REGION,
    lat_deg: float = LAT_DEG,
    lon_deg: float = LON_DEG,
    folder_danych: str = FOLDER_DANYCH,
    folder_cache_topo: str = FOLDER_CACHE_TOPO,
    krok_minut: int = 60,
) -> tuple[list[list], dict[str, list[float]]]:
    """
    Oblicza i zwraca:
      1) 7-kolumnową tabelę `tabela_naslonecznienia`:
         [
           [
             data_i_godzina_lokalna_str,                 # kol. 1: 'YYYY-MM-DD HH:MM'
             natezenie_pozioma_W_m2,                     # kol. 2: I_S * sin(z) * alpha [W/m^2]
             energia_skumulowana_pozioma_J_m2,           # kol. 3: energia na płaszczyźnie poziomej [J/m^2]
             natezenie_pionowa_W_m2,                     # kol. 4: I_S * cos(z) * alpha (płaszczyzna prostopadła do gruntu) [W/m^2]
             energia_skumulowana_pionowa_J_m2,           # kol. 5: energia na płaszczyźnie prostopadłej do gruntu [J/m^2]
             natezenie_bez_elewacji_W_m2,                # kol. 6: I_S * alpha (z pominięciem kąta elewacji z) [W/m^2]
             energia_skumulowana_bez_elewacji_J_m2,      # kol. 7: energia skumulowana z pominięciem kąta elewacji [J/m^2]
           ],
           ...
         ]
      2) słownik serii kątowych do wykresu widoczności nad górami:
         - 'wysokosc_gor_deg': kątowa wysokość horyzontu topograficznego w kierunku Słońca [°]
         - 'wysokosc_gornej_krawedzi_slonca_deg': wysokość kątowa górnej krawędzi tarczy Słońca [°]
    """
    strefa_iana = define_IANA_zone(kraj, region)
    if strefa_iana.startswith("Błąd"):
        raise ValueError(f"{strefa_iana} dla kraju '{kraj}'.")

    data_poczatek_utc = convert_to_utc(data_poczatek_lokalna, strefa_iana)
    data_koniec_utc = convert_to_utc(data_koniec_lokalna, strefa_iana)

    punkty_czasu_utc = generuj_punkty_czasowe(
        data_poczatek_utc,
        data_koniec_utc,
        krok_minut=krok_minut,
    )

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
        sciezka = Path(folder_danych) / f"{rok}.csv"
        if not sciezka.exists():
            dostepne = sorted(p.name for p in Path(folder_danych).glob("*.csv"))
            raise FileNotFoundError(
                f"Brak pliku z danymi: {sciezka} (czas lokalny po przeliczeniu na UTC wymaga roku {rok}). "
                f"Dostępne pliki w '{folder_danych}': {dostepne}"
            )
        with open(sciezka, mode="r", encoding="utf-8", newline="") as plik:
            reader = csv.reader(plik)
            next(reader)
            for wiersz in reader:
                dane_godzinowe[wiersz[0]] = [float(x) for x in wiersz[1:7]]

    tabela_naslonecznienia: list[list] = []
    wysokosc_gor_deg: list[float] = []
    wysokosc_gornej_krawedzi_slonca_deg: list[float] = []

    energia_pozioma_j_m2 = 0.0
    energia_pionowa_j_m2 = 0.0
    energia_bez_elewacji_j_m2 = 0.0
    poprzedni_dt_utc: datetime | None = None
    poprzednie_natezenie_poz: float = 0.0
    poprzednie_natezenie_pion: float = 0.0
    poprzednie_natezenie_bez_elewacji: float = 0.0

    for dt_utc in punkty_czasu_utc:
        if dt_utc.minute == 0 and dt_utc.second == 0:
            klucz = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
            if klucz not in dane_godzinowe:
                raise ValueError(f"Nie znaleziono rekordu {klucz} w folderze '{folder_danych}'.")
            wiersz_6 = dane_godzinowe[klucz]
        else:
            interp = interpoluj_polozenie(
                dt_utc.strftime("%Y-%m-%d %H:%M"),
                folder=folder_danych,
            )
            wiersz_6 = [float(x) for x in interp[1:7]]

        z_rad, azymut_rad, dystans_slonce_km = oblicz_pozycje_slonca_na_niebie_ksiezyca(
            dt_utc=dt_utc,
            wiersz_6=wiersz_6,
            lat_deg=lat_deg,
            lon_deg=lon_deg,
            wysokosc_obs_m=topografia.wysokosc_obserwatora_m,
        )

        rho_sun = math.asin(min(1.0, R_SUN / dystans_slonce_km))
        kat_gor_rad = topografia.kat_horyzontu(azymut_rad)

        wysokosc_gor_deg.append(math.degrees(kat_gor_rad))
        wysokosc_gornej_krawedzi_slonca_deg.append(math.degrees(z_rad + rho_sun))

        alpha = oblicz_widoczny_ulamek_tarczy_slonca(
            z_rad=z_rad,
            azymut_rad=azymut_rad,
            dystans_slonce_km=dystans_slonce_km,
            topografia=topografia,
        )

        # 1) Płaszczyzna pozioma (równoległa do gruntu): rzut cos(90° - z) = sin(z)
        sin_z_dodatni = max(0.0, math.sin(z_rad))
        natezenie_poz_w_m2 = I_S * sin_z_dodatni * alpha

        # 2) Płaszczyzna pionowa (prostopadła do gruntu, skierowana na azymut Słońca): rzut cos(z)
        cos_z_dodatni = max(0.0, math.cos(z_rad))
        natezenie_pion_w_m2 = I_S * cos_z_dodatni * alpha

        # 3) Płaszczyzna z pominięciem kąta elewacji z (panel skierowany bezpośrednio do Słońca)
        natezenie_bez_elewacji_w_m2 = I_S * alpha

        if poprzedni_dt_utc is not None:
            dt_sekundy = (dt_utc - poprzedni_dt_utc).total_seconds()
            energia_pozioma_j_m2 += 0.5 * (poprzednie_natezenie_poz + natezenie_poz_w_m2) * dt_sekundy
            energia_pionowa_j_m2 += 0.5 * (poprzednie_natezenie_pion + natezenie_pion_w_m2) * dt_sekundy
            energia_bez_elewacji_j_m2 += (
                0.5 * (poprzednie_natezenie_bez_elewacji + natezenie_bez_elewacji_w_m2) * dt_sekundy
            )

        czas_lokalny_str = convert_time_zone(dt_utc.strftime("%Y-%m-%d %H:%M"), strefa_iana)
        tabela_naslonecznienia.append(
            [
                czas_lokalny_str,
                natezenie_poz_w_m2,
                energia_pozioma_j_m2,
                natezenie_pion_w_m2,
                energia_pionowa_j_m2,
                natezenie_bez_elewacji_w_m2,
                energia_bez_elewacji_j_m2,
            ]
        )

        poprzedni_dt_utc = dt_utc
        poprzednie_natezenie_poz = natezenie_poz_w_m2
        poprzednie_natezenie_pion = natezenie_pion_w_m2
        poprzednie_natezenie_bez_elewacji = natezenie_bez_elewacji_w_m2

    dane_katowe = {
        "wysokosc_gor_deg": wysokosc_gor_deg,
        "wysokosc_gornej_krawedzi_slonca_deg": wysokosc_gornej_krawedzi_slonca_deg,
    }
    return tabela_naslonecznienia, dane_katowe


def generuj_tabele_naslonecznienia(
    data_poczatek_lokalna: str,
    data_koniec_lokalna: str,
    kraj: str = KRAJ,
    region: str | None = REGION,
    lat_deg: float = LAT_DEG,
    lon_deg: float = LON_DEG,
    folder_danych: str = FOLDER_DANYCH,
    folder_cache_topo: str = FOLDER_CACHE_TOPO,
    krok_minut: int = 60,
) -> list[list]:
    """
    Generuje 7-kolumnową tabelę `tabela_naslonecznienia`:
      1. data i godzina lokalna ('YYYY-MM-DD HH:MM')
      2. natężenie promieniowania na płaszczyźnie poziomej [W/m^2]
      3. energia skumulowana na płaszczyźnie poziomej od początku przedziału [J/m^2]
      4. moc/natężenie na płaszczyźnie prostopadłej do gruntu skierowanej do Słońca [W/m^2]
      5. energia skumulowana na płaszczyźnie prostopadłej do gruntu od początku przedziału [J/m^2]
      6. natężenie promieniowania z pominięciem kąta elewacji (I_S * alpha) [W/m^2]
      7. energia skumulowana z pominięciem kąta elewacji od początku przedziału [J/m^2]
    """
    tabela, _ = generuj_dane_naslonecznienia(
        data_poczatek_lokalna=data_poczatek_lokalna,
        data_koniec_lokalna=data_koniec_lokalna,
        kraj=kraj,
        region=region,
        lat_deg=lat_deg,
        lon_deg=lon_deg,
        folder_danych=folder_danych,
        folder_cache_topo=folder_cache_topo,
        krok_minut=krok_minut,
    )
    return tabela


# ==============================================================================
# WIZUALIZIZACJA W MATPLOTLIB (7 WYKRESÓW)
# ==============================================================================
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




if __name__ == "__main__":
    strefa = define_IANA_zone(KRAJ, REGION)
    tabela_naslonecznienia, dane_katowe = generuj_dane_naslonecznienia(
        data_poczatek_lokalna=DATA_POCZATEK,
        data_koniec_lokalna=DATA_KONIEC,
        kraj=KRAJ,
        region=REGION,
        lat_deg=LAT_DEG,
        lon_deg=LON_DEG,
        folder_danych=FOLDER_DANYCH,
        folder_cache_topo=FOLDER_CACHE_TOPO,
    )

    '''print(f"Wygenerowano wierszy: {len(tabela_naslonecznienia)}")
    for wiersz in tabela_naslonecznienia[:10]:
        print(
            f"{wiersz[0]} | "
            f"I_poz = {wiersz[1]:7.2f} W/m^2 | E_poz = {wiersz[2]:13.2f} J/m^2 | "
            f"I_pion = {wiersz[3]:7.2f} W/m^2 | E_pion = {wiersz[4]:13.2f} J/m^2 | "
            f"I_bez_el = {wiersz[5]:7.2f} W/m^2 | E_bez_el = {wiersz[6]:13.2f} J/m^2"
        )

    rysuj_wykresy_naslonecznienia(
        tabela_naslonecznienia,
        LAT_DEG,
        LON_DEG,
        strefa,
        wysokosc_gor_deg=dane_katowe["wysokosc_gor_deg"],
        wysokosc_gornej_krawedzi_slonca_deg=dane_katowe["wysokosc_gornej_krawedzi_slonca_deg"],
    )'''
