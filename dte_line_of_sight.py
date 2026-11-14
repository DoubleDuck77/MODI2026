"""DTE (Direct-to-Earth): czy z punktu na Księżycu jest linia wzroku do Ziemi.

Uwzględnia:
- topografię terenu: horyzont liczony dokładnie tak jak klawisz C w ``newlunar.py``
  (``LunarTerrain3D.update_observer``), tylko automatycznie i na prawdziwym DEM LOLA,
  zapisywany do ``horizons/*.csv`` w tym samym formacie co ``horizon.csv``;
- librację Księżyca: orientacja Księżyca z modelu IAU (Archinal i in. 2011, WGCCRE),
  z libracją fizyczną, w układzie Mean-Earth/polar axis (tym samym, co LOLA); libracja
  optyczna wynika z prawdziwych pozycji Księżyca z ``coords/<rok>.csv`` (JPL Horizons).

Użycie:
    python3 dte_line_of_sight.py point   --t 2026-01-01T00:00:00Z --lat 0 --lon 90
    python3 dte_line_of_sight.py windows --start 2026-01-01T00:00:00Z --end 2026-02-01T00:00:00Z --lat 0 --lon 90

Konwencje jak w ``docs/ARCHITECTURE.md``: czas UTC (ISO 8601), kąty w stopniach, azymut od N
zgodnie z ruchem wskazówek (E = 90°), długość wschodnia dodatnia. Pola wyniku mają nazwy z
kontraktu ``line_of_sight`` (``backend/app/features/line_of_sight/contract.py``).

Import modułu niczego nie wypisuje ani nie pobiera; DEM i ``newlunar`` ładują się przy
pierwszym użyciu.
"""

import contextlib
import csv
import io
import math
import os
import sys
import types
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

REPO_DIR = Path(__file__).resolve().parent
TEXTURES_DIR = REPO_DIR / "Textures"
HORIZONS_DIR = REPO_DIR / "horizons"

R_MOON_KM = 1737.4
R_EARTH_KM = 6371.0
OBLIQUITY_J2000_DEG = 23.4392911

DATA_START = datetime(2000, 1, 1, tzinfo=timezone.utc)   # pierwszy rekord coords/2000.csv
DATA_END = datetime(2100, 1, 1, tzinfo=timezone.utc)     # jedyny rekord coords/2100.csv
J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


# --------------------------- EFEMERYDA I ORIENTACJA ---------------------------


def _to_utc(t: datetime) -> datetime:
    """Czas bez strefy = UTC, z offsetem → UTC; poza zakresem danych → ValueError."""
    t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
    if not DATA_START <= t <= DATA_END:
        raise ValueError(
            f"czas {t.isoformat()} poza zakresem danych [{DATA_START.isoformat()}, {DATA_END.isoformat()}]"
        )
    return t


def parse_utc(s: str) -> datetime:
    """ISO 8601 → aware UTC. Akceptuje sufiks ``Z`` (także na Pythonie 3.10), offset i brak strefy."""
    text = s.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"niepoprawny czas ISO 8601: {s!r}") from None
    return _to_utc(t)


def _hours_since_start(t: datetime) -> float:
    return (t - DATA_START).total_seconds() / 3600.0


def _year_start_hour(year: int) -> int:
    return int((datetime(year, 1, 1, tzinfo=timezone.utc) - DATA_START) // timedelta(hours=1))


class Ephemeris:
    """Geocentryczne położenie Księżyca (ekliptyka J2000, km) z ``coords/<rok>.csv``.

    Pliki są w METRACH (|moon| ≈ 3.6e8), co godzinę i bez przerw; ``2100.csv`` ma tylko
    2100-01-01 00:00. Etykiety czasu są w TDB — traktujemy je jak UTC (różnica ~69 s).
    Między godzinami interpolacja liniowa.
    """

    def __init__(self, coords_dir: Optional[Path] = None):
        env_dir = os.environ.get("MODI_COORDS_DIR")
        self.coords_dir = Path(coords_dir or env_dir or REPO_DIR / "coords")
        self._years = {}

    def _rows(self, year: int) -> np.ndarray:
        rows = self._years.get(year)
        if rows is None:
            path = self.coords_dir / f"{year}.csv"
            if not path.is_file():
                raise RuntimeError(f"brak pliku efemeryd {path}")
            rows = np.loadtxt(path, delimiter=",", skiprows=1, usecols=range(1, 7), ndmin=2) / 1000.0
            expected = 1 if year == DATA_END.year else _year_start_hour(year + 1) - _year_start_hour(year)
            if len(rows) != expected:
                raise RuntimeError(f"{path} ma {len(rows)} wierszy, oczekiwano {expected} (dane co godzinę)")
            self._years[year] = rows
        return rows

    def moon_geo_km(self, times: Sequence[datetime]) -> np.ndarray:
        """Wektory Ziemia→Księżyc [km], kształt (N, 3)."""
        hours = np.array([_hours_since_start(_to_utc(t)) for t in times], dtype=np.float64)
        last = _year_start_hour(DATA_END.year)
        i0 = np.clip(np.floor(hours).astype(np.int64), 0, last - 1)
        frac = (hours - i0)[:, None]

        y_first = (DATA_START + timedelta(hours=int(i0.min()))).year
        y_last = (DATA_START + timedelta(hours=int(i0.max()) + 1)).year
        table = np.vstack([self._rows(y)[:, 3:6] for y in range(y_first, y_last + 1)])
        base = _year_start_hour(y_first)
        a = table[i0 - base]
        b = table[i0 + 1 - base]
        return a + frac * (b - a)


def _rz(a: np.ndarray) -> np.ndarray:
    """Obrót układu wokół osi z o kąty ``a`` [rad], kształt (N, 3, 3)."""
    c, s = np.cos(a), np.sin(a)
    m = np.zeros(a.shape + (3, 3))
    m[:, 0, 0], m[:, 0, 1] = c, s
    m[:, 1, 0], m[:, 1, 1] = -s, c
    m[:, 2, 2] = 1.0
    return m


def _rx(a: np.ndarray) -> np.ndarray:
    """Obrót układu wokół osi x o kąty ``a`` [rad], kształt (N, 3, 3)."""
    c, s = np.cos(a), np.sin(a)
    m = np.zeros(a.shape + (3, 3))
    m[:, 0, 0] = 1.0
    m[:, 1, 1], m[:, 1, 2] = c, s
    m[:, 2, 1], m[:, 2, 2] = -s, c
    return m


_EPS = math.radians(OBLIQUITY_J2000_DEG)
_ECL_TO_EQ = np.array([
    [1.0, 0.0, 0.0],
    [0.0, math.cos(_EPS), -math.sin(_EPS)],
    [0.0, math.sin(_EPS), math.cos(_EPS)],
])


def moon_me_matrix(d: np.ndarray) -> np.ndarray:
    """Macierze: ekliptyka J2000 → układ Księżyca Mean-Earth (model IAU, Archinal i in. 2011).

    ``d`` to doby od J2000.0 (2000-01-01 12:00). Model zawiera librację fizyczną; razem z
    prawdziwym położeniem Księżyca daje pełną librację (optyczną + fizyczną).
    """
    d = np.atleast_1d(np.asarray(d, dtype=np.float64))
    T = d / 36525.0
    E = {k: np.radians(v) for k, v in {
        1: 125.045 - 0.0529921 * d, 2: 250.089 - 0.1059842 * d, 3: 260.008 + 13.0120009 * d,
        4: 176.625 + 13.3407154 * d, 5: 357.529 + 0.9856003 * d, 6: 311.589 + 26.4057084 * d,
        7: 134.963 + 13.0649930 * d, 8: 276.617 + 0.3287146 * d, 9: 34.226 + 1.7484877 * d,
        10: 15.134 - 0.1589763 * d, 11: 119.743 + 0.0036096 * d, 12: 239.961 + 0.1643573 * d,
        13: 25.053 + 12.9590088 * d,
    }.items()}
    sin, cos = np.sin, np.cos
    alpha0 = (269.9949 + 0.0031 * T - 3.8787 * sin(E[1]) - 0.1204 * sin(E[2]) + 0.0700 * sin(E[3])
              - 0.0172 * sin(E[4]) + 0.0072 * sin(E[6]) - 0.0052 * sin(E[10]) + 0.0043 * sin(E[13]))
    delta0 = (66.5392 + 0.0130 * T + 1.5419 * cos(E[1]) + 0.0239 * cos(E[2]) - 0.0278 * cos(E[3])
              + 0.0068 * cos(E[4]) - 0.0029 * cos(E[6]) + 0.0009 * cos(E[7]) + 0.0008 * cos(E[10])
              - 0.0009 * cos(E[13]))
    W = (38.3213 + 13.17635815 * d - 1.4e-12 * d * d + 3.5610 * sin(E[1]) + 0.1208 * sin(E[2])
         - 0.0642 * sin(E[3]) + 0.0158 * sin(E[4]) + 0.0252 * sin(E[5]) - 0.0066 * sin(E[6])
         - 0.0047 * sin(E[7]) - 0.0046 * sin(E[8]) + 0.0028 * sin(E[9]) + 0.0052 * sin(E[10])
         + 0.0040 * sin(E[11]) + 0.0019 * sin(E[12]) - 0.0044 * sin(E[13]))
    eq_to_me = _rz(np.radians(W)) @ _rx(np.radians(90.0 - delta0)) @ _rz(np.radians(90.0 + alpha0))
    return eq_to_me @ _ECL_TO_EQ


def days_since_j2000(times: Sequence[datetime]) -> np.ndarray:
    return np.array([(_to_utc(t) - J2000).total_seconds() / 86400.0 for t in times], dtype=np.float64)


def earth_in_moon_frame_km(eph: Ephemeris, times: Sequence[datetime]) -> np.ndarray:
    """Wektory środek Księżyca → środek Ziemi [km] w układzie Księżyca ME, kształt (N, 3)."""
    m = moon_me_matrix(days_since_j2000(times))
    return np.einsum("nij,nj->ni", m, -eph.moon_geo_km(times))


# --------------------------- TEREN / HORYZONT ---------------------------
#
# Horyzont liczy kod newlunar.py (LunarTerrain3D.update_observer + export_horizon_csv, czyli klawisz C).
# Sam newlunar bierze DEM z Textures/moon_dem.npy (SVS ldem_3_8bit.jpg: 1024×512, ~10.7 km/px,
# 8 bitów ≈ 78 m na poziom). Do DTE podajemy mu dokładniejszy LOLA LDEM_16 (5760×2880, ~1.9 km/px,
# 0.5 m) w tym samym formacie (float32, km względem 1737.4 km, wiersz 0 = lat +90, kolumna 0 =
# lon −180), zapisany w Textures/moon_dem_v2.npy — tego cache używa też lunar_stellarium.py.

LDEM16_URL = ("https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/"
              "data/lola_gdr/cylindrical/img/ldem_16.img")
LDEM16_SHAPE = (2880, 5760)                      # 16 px/°, kolumna 0 = lon 0°E, środki pikseli
LDEM16_BYTES = LDEM16_SHAPE[0] * LDEM16_SHAPE[1] * 2
LDEM16_RAW = TEXTURES_DIR / "ldem_16.img"
NEWLUNAR_DEM_CACHE = TEXTURES_DIR / "moon_dem_v2.npy"
# horizon.csv z klawisza C: kolumna 0 = azymut, kolumna 1 = elewacja horyzontu (stary format
# newlunar miał nagłówek "Altitude_deg" i 2 kolumny, obecny "Horizon_Altitude_deg" i 10 kolumn)
HORIZON_AZ_COL = "Azimuth_deg"
HORIZON_ALT_COLS = ("Horizon_Altitude_deg", "Altitude_deg")
MAX_HORIZON_GAP_DEG = 1.0        # największa dopuszczalna luka azymutu w horizon.csv
OBSERVER_MATCH_TOL_DEG = 1e-4    # horizon.csv zapisuje położenie obserwatora z 6 miejscami po przecinku

# newlunar.sample_dem_bilinear dodaje do DEM sztuczny „detail” (±55 m, sinusy w kątach). Jego okres
# wschód–zachód maleje jak cos(lat), więc przy biegunach tworzy strome, nieistniejące zbocza.
# Przy |lat| > 89.9° próbkowanie mapy równoodległościowej się degeneruje.
POLAR_WARNING_LAT_DEG = 80.0
POLE_SINGULAR_LAT_DEG = 89.9


def horizon_warnings(lat_deg: float) -> list:
    """Ostrzeżenia o wiarygodności horyzontu z newlunar (klawisz C) dla danej szerokości."""
    warnings = []
    if abs(lat_deg) > POLE_SINGULAR_LAT_DEG:
        warnings.append(f"|lat| > {POLE_SINGULAR_LAT_DEG:g}°: próbkowanie DEM w newlunar degeneruje się "
                        "przy biegunie — horyzont i dte_contact są niewiarygodne")
    elif abs(lat_deg) >= POLAR_WARNING_LAT_DEG:
        warnings.append(f"|lat| ≥ {POLAR_WARNING_LAT_DEG:g}°: sztuczny „detail” ±55 m w newlunar zawyża tu "
                        "horyzont (p95: ≈2° przy 80°, ≈9–13° przy 85°, ≈21–24° przy 88°) — dte_contact "
                        "może być fałszywie false")
    return warnings


def ldem16_to_newlunar(raw_path: Path) -> np.ndarray:
    """LDEM_16 (int16 LE, 0.5 m/DN względem 1737.4 km) → mapa wysokości w formacie newlunar [km]."""
    raw_path = Path(raw_path)
    size = raw_path.stat().st_size if raw_path.exists() else 0
    if size != LDEM16_BYTES:
        raise RuntimeError(
            f"niepełny plik {raw_path} ({size} B, oczekiwano {LDEM16_BYTES} B) — "
            f"usuń go i uruchom ponownie albo pobierz ręcznie z {LDEM16_URL}"
        )
    dn = np.memmap(raw_path, dtype="<i2", mode="r", shape=LDEM16_SHAPE)
    km = dn.astype(np.float32) * np.float32(0.5 / 1000.0)
    # kolumna 0 to lon 0°E → przesuwamy o pół obwodu, żeby kolumna 0 była lon −180° (jak w newlunar)
    return np.ascontiguousarray(np.roll(km, LDEM16_SHAPE[1] // 2, axis=1))


def _download(url: str, dest: Path) -> None:
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "modi2026-dte"})
    print(f"[DTE] Pobieranie DEM LOLA: {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done, next_report = 0, 0.1
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total and done / total >= next_report:
                    print(f"[DTE]   {done * 100 // total}%", file=sys.stderr)
                    next_report += 0.1
    except OSError as e:
        raise RuntimeError(f"nie udało się pobrać {url}: {e}; pobierz plik ręcznie do {dest}") from e
    os.replace(part, dest)


def ensure_newlunar_dem() -> np.ndarray:
    """Mapa wysokości [km] z cache newlunar; przy braku cache pobiera LDEM_16 i go tworzy."""
    if NEWLUNAR_DEM_CACHE.exists():
        return np.load(NEWLUNAR_DEM_CACHE)
    TEXTURES_DIR.mkdir(parents=True, exist_ok=True)
    if not LDEM16_RAW.exists():
        _download(LDEM16_URL, LDEM16_RAW)
    dem = ldem16_to_newlunar(LDEM16_RAW)
    tmp = NEWLUNAR_DEM_CACHE.with_name(NEWLUNAR_DEM_CACHE.name + ".part")
    with open(tmp, "wb") as f:
        np.save(f, dem)
    os.replace(tmp, NEWLUNAR_DEM_CACHE)
    LDEM16_RAW.unlink()
    print(f"[DTE] Zapisano DEM LOLA dla newlunar: {NEWLUNAR_DEM_CACHE}", file=sys.stderr)
    return dem


_NEWLUNAR = None
_TERRAIN = None


def _newlunar():
    """Import newlunar.py bez okna; gdy brak pygame, podstawiamy pusty moduł (nie wołamy pygame)."""
    global _NEWLUNAR
    if _NEWLUNAR is None:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")   # pygame wypisuje baner na stdout
        try:
            import pygame  # noqa: F401
        except ImportError:
            sys.modules["pygame"] = types.ModuleType("pygame")
        if str(REPO_DIR) not in sys.path:
            sys.path.insert(0, str(REPO_DIR))
        import newlunar
        _NEWLUNAR = newlunar
    return _NEWLUNAR


def _terrain():
    """Jedna instancja newlunar.LunarTerrain3D na proces (albedo nie jest potrzebne do horyzontu)."""
    global _TERRAIN
    if _TERRAIN is None:
        _TERRAIN = _newlunar().LunarTerrain3D(ensure_newlunar_dem(), np.zeros((2, 2, 3), dtype=np.float32))
    return _TERRAIN


def _check_observer(lat_deg: float, lon_deg: float, antenna_height_m: float) -> None:
    if not -90.0 <= lat_deg <= 90.0:
        raise ValueError(f"lat_deg={lat_deg} poza zakresem [-90, 90]")
    if not -180.0 <= lon_deg <= 180.0:
        raise ValueError(f"lon_deg={lon_deg} poza zakresem [-180, 180]")
    if not antenna_height_m >= 0.0:
        raise ValueError(f"antenna_height_m={antenna_height_m} musi być >= 0")


def generate_horizon_csv(lat_deg: float, lon_deg: float, antenna_height_m: float = 2.0,
                         out_dir: Optional[Path] = None) -> Tuple[Path, float]:
    """Horyzont terenowy jak klawisz C w newlunar.py, bez okna. Zwraca (ścieżka CSV, grunt [m])."""
    _check_observer(lat_deg, lon_deg, antenna_height_m)
    terrain = _terrain()
    terrain.update_observer(lat_deg, lon_deg, eye_height_m=antenna_height_m)

    out_dir = Path(out_dir or HORIZONS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"horizon_lat{lat_deg:+.4f}_lon{lon_deg:+.4f}_h{antenna_height_m:g}m.csv"
    # zapisuje sam newlunar (ta sama funkcja co klawisz C), przez plik tymczasowy, żeby równoległy
    # odczyt nigdy nie trafił na urwany plik; jego komunikat "[OK] ..." nie może trafić na stdout (JSON)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.part")
    with contextlib.redirect_stdout(io.StringIO()):
        terrain.export_horizon_csv(str(tmp))
    os.replace(tmp, path)
    return path, float(terrain.obs_elev_km) * 1000.0


def load_horizon_csv(path: Path) -> Tuple[np.ndarray, np.ndarray, dict]:
    """Czyta horizon.csv z klawisza C (obecny 10-kolumnowy albo stary 2-kolumnowy format).

    Zwraca (azymuty [deg], elewacje horyzontu [deg], meta), gdzie ``meta`` ma kolumny
    ``Observer_*`` z pierwszego wiersza (pusty słownik dla starego formatu).
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"{path}: brak pliku horyzontu")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = [c.strip() for c in rows[0]] if rows else []
    if len(header) < 2 or header[0] != HORIZON_AZ_COL or header[1] not in HORIZON_ALT_COLS:
        raise ValueError(f"{path}: oczekiwano nagłówka {HORIZON_AZ_COL},{HORIZON_ALT_COLS[0]},… "
                         f"(plik z klawisza C w newlunar.py)")
    try:
        data = np.array([[float(r[0]), float(r[1])] for r in rows[1:] if r], dtype=np.float64)
        meta = {k: float(v) for k, v in zip(header, rows[1]) if k.startswith("Observer_")} if len(rows) > 1 else {}
    except (ValueError, IndexError):
        raise ValueError(f"{path}: niepoprawny wiersz danych (oczekiwano liczb)") from None
    if len(data) < 2 or not np.all(np.isfinite(data)):
        raise ValueError(f"{path}: za mało wierszy lub wartości nieskończone")
    az, alt = data[:, 0], data[:, 1]
    if az[0] < 0.0 or az[-1] >= 360.0 or np.any(np.diff(az) <= 0.0):
        raise ValueError(f"{path}: azymuty muszą rosnąć w zakresie [0, 360)")
    gap = float(np.max(np.diff(np.append(az, az[0] + 360.0))))
    if gap > MAX_HORIZON_GAP_DEG:
        raise ValueError(
            f"{path}: niepełny horyzont — luka azymutu {gap:g}° (dopuszczalne ≤ {MAX_HORIZON_GAP_DEG:g}°; "
            f"plik z klawisza C ma 480 wierszy co 0.75°)"
        )
    return az, alt, meta


def horizon_at(az_tab: np.ndarray, alt_tab: np.ndarray, az_deg) -> np.ndarray:
    """Elewacja horyzontu [deg] w azymutach ``az_deg`` (interpolacja okresowa przez 0°/360°)."""
    return np.interp(np.asarray(az_deg, dtype=np.float64) % 360.0, az_tab, alt_tab, period=360.0)


# --------------------------- WIDOCZNOŚĆ (DTE) ---------------------------


def disk_fraction(clearance_deg: float, radius_deg: float) -> float:
    """Ułamek tarczy Ziemi nad horyzontem (horyzont lokalnie płaski na szerokości tarczy)."""
    if radius_deg <= 0.0:
        return 1.0 if clearance_deg > 0.0 else 0.0
    x = max(-1.0, min(1.0, clearance_deg / radius_deg))
    return 1.0 - (math.acos(x) - x * math.sqrt(1.0 - x * x)) / math.pi


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _horizon_source(lat_deg: float, lon_deg: float, antenna_height_m: float,
                    horizon_csv: Optional[Path]):
    """(ścieżka CSV, grunt [m] albo None, azymuty, elewacje). Bez ``horizon_csv`` generuje plik jak klawisz C.

    Gotowy plik z klawisza C zapisuje, dla jakiego punktu i wysokości oka był liczony — horyzont
    z innego miejsca dałby po cichu zły wynik, więc niezgodność z argumentami to błąd.
    """
    if horizon_csv is None:
        path, ground_m = generate_horizon_csv(lat_deg, lon_deg, antenna_height_m)
        az_tab, alt_tab, _ = load_horizon_csv(path)
        return path, ground_m, az_tab, alt_tab

    path = Path(horizon_csv)
    az_tab, alt_tab, meta = load_horizon_csv(path)
    if "Observer_Lat_deg" in meta and "Observer_Lon_deg" in meta:
        f_lat, f_lon = meta["Observer_Lat_deg"], meta["Observer_Lon_deg"]
        d_lon = abs((f_lon - lon_deg + 180.0) % 360.0 - 180.0)
        if abs(f_lat - lat_deg) > OBSERVER_MATCH_TOL_DEG or d_lon > OBSERVER_MATCH_TOL_DEG:
            raise ValueError(f"{path} jest dla punktu lat={f_lat:g}, lon={f_lon:g}, "
                             f"a podano lat={lat_deg:g}, lon={lon_deg:g}")
    f_height = meta.get("Observer_Height_above_surface_m")
    if f_height is not None and abs(f_height - antenna_height_m) > 0.01:
        raise ValueError(f"{path} jest dla wysokości {f_height:g} m nad gruntem, a podano "
                         f"--antenna-height-m {antenna_height_m:g}")
    ground_km = meta.get("Observer_Elevation_km")
    return path, None if ground_km is None else ground_km * 1000.0, az_tab, alt_tab


def _evaluate(times: Sequence[datetime], lat_deg: float, lon_deg: float, antenna_height_m: float,
              min_elevation_deg: float, horizon_csv: Optional[Path], eph: Optional[Ephemeris]) -> dict:
    """Wszystkie wielkości DTE dla N chwil (wektorowo), już zaokrąglone i spójne ze sobą."""
    _check_observer(lat_deg, lon_deg, antenna_height_m)
    if not math.isfinite(min_elevation_deg):
        raise ValueError("min_elevation_deg musi być liczbą skończoną")
    eph = eph or Ephemeris()
    path, ground_m, az_tab, alt_tab = _horizon_source(lat_deg, lon_deg, antenna_height_m, horizon_csv)

    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.cross(up, east)
    r_obs = R_MOON_KM + ((ground_m or 0.0) + antenna_height_m) / 1000.0

    earth = earth_in_moon_frame_km(eph, times)                  # środek Księżyca → Ziemia
    v = earth - r_obs * up                                        # obserwator → Ziemia
    dist = np.linalg.norm(v, axis=1)
    alt = np.degrees(np.arcsin(np.clip((v @ up) / dist, -1.0, 1.0)))
    az = np.degrees(np.arctan2(v @ east, v @ north)) % 360.0
    rho = np.degrees(np.arcsin(R_EARTH_KM / dist))
    hor = horizon_at(az_tab, alt_tab, az)
    e_norm = np.linalg.norm(earth, axis=1)

    alt_r, hor_r = np.round(alt, 4), np.round(hor, 4)
    clearance = np.round(alt_r - hor_r, 4)
    fraction = np.array([round(disk_fraction(c, r), 4) for c, r in zip(clearance, rho)])
    return {
        "path": path,
        "ground_m": ground_m,
        "alt": alt_r,
        "az": np.round(az, 4) % 360.0,
        "dist": np.round(dist, 1),
        "rho": np.round(rho, 4),
        "lib_lat": np.round(np.degrees(np.arcsin(earth[:, 2] / e_norm)), 4),
        "lib_lon": np.round(np.degrees(np.arctan2(earth[:, 1], earth[:, 0])), 4),
        "hor": hor_r,
        "clearance": clearance,
        "fraction": fraction,
        "contact": clearance > min_elevation_deg,
    }


def dte_point(t: datetime, lat_deg: float, lon_deg: float, *, antenna_height_m: float = 2.0,
              min_elevation_deg: float = 0.0, horizon_csv: Optional[Path] = None,
              eph: Optional[Ephemeris] = None) -> dict:
    """Czy w chwili ``t`` jest kontakt DTE z Ziemią (pola jak w kontrakcie ``LineOfSight`` + dodatki)."""
    t = _to_utc(t)
    r = _evaluate([t], lat_deg, lon_deg, antenna_height_m, min_elevation_deg, horizon_csv, eph)
    fraction = float(r["fraction"][0])
    return {
        "t": _iso(t),
        "observer": {"lat_deg": float(lat_deg), "lon_deg": float(lon_deg)},
        "observer_elevation_m": None if r["ground_m"] is None else round(r["ground_m"], 1),
        "antenna_height_m": float(antenna_height_m),
        "earth": {"alt_deg": float(r["alt"][0]), "az_deg": float(r["az"][0]),
                  "distance_km": float(r["dist"][0])},
        "earth_angular_radius_deg": float(r["rho"][0]),
        "libration": {"lat_deg": float(r["lib_lat"][0]), "lon_deg": float(r["lib_lon"][0])},
        "horizon_elevation_deg": float(r["hor"][0]),
        "clearance_deg": float(r["clearance"][0]),
        "visible_disk_fraction": fraction,
        "earth_visible": fraction > 0.0,
        "min_elevation_deg": float(min_elevation_deg),
        "dte_contact": bool(r["contact"][0]),
        "horizon_csv": str(r["path"]),
        "warnings": horizon_warnings(lat_deg),
    }


def dte_windows(start: datetime, end: datetime, lat_deg: float, lon_deg: float, *, step_hours: int = 1,
                antenna_height_m: float = 2.0, min_elevation_deg: float = 0.0,
                horizon_csv: Optional[Path] = None, eph: Optional[Ephemeris] = None) -> dict:
    """Okna kontaktu DTE w ``[start, end]`` próbkowane co ``step_hours`` (jak kontrakt ``VisibilityWindows``)."""
    start, end = _to_utc(start), _to_utc(end)
    if isinstance(step_hours, bool) or not isinstance(step_hours, int) or step_hours < 1:
        raise ValueError(f"step_hours={step_hours!r} musi być liczbą całkowitą >= 1")
    if start >= end:
        raise ValueError("start musi być wcześniejszy niż end")
    step = timedelta(hours=step_hours)
    times = [start + k * step for k in range((end - start) // step + 1)]
    r = _evaluate(times, lat_deg, lon_deg, antenna_height_m, min_elevation_deg, horizon_csv, eph)

    windows, total = [], timedelta(0)
    contact, i = r["contact"], 0
    while i < len(times):
        if not contact[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(times) and contact[j + 1]:
            j += 1
        w_start, w_end = times[i], min(times[j] + step, end)
        if w_end > w_start:
            windows.append({"start": _iso(w_start), "end": _iso(w_end),
                            "max_clearance_deg": float(r["clearance"][i:j + 1].max())})
            total += w_end - w_start
        i = j + 1

    return {
        "observer": {"lat_deg": float(lat_deg), "lon_deg": float(lon_deg)},
        "start": _iso(start),
        "end": _iso(end),
        "step_hours": step_hours,
        "min_elevation_deg": float(min_elevation_deg),
        "horizon_csv": str(r["path"]),
        "samples": len(times),
        "windows": windows,
        "visible_fraction": round(total / (end - start), 4),
        "warnings": horizon_warnings(lat_deg),
    }


# --------------------------- CLI ---------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lat", type=float, required=True, help="szerokość selenograficzna [deg]")
    common.add_argument("--lon", type=float, required=True, help="długość selenograficzna, E dodatnia [deg]")
    common.add_argument("--antenna-height-m", type=float, default=2.0,
                        help="wysokość anteny nad gruntem [m] (domyślnie 2, jak suwak w newlunar)")
    common.add_argument("--min-elevation-deg", type=float, default=0.0,
                        help="minimalny zapas środka Ziemi nad horyzontem terenowym [deg]")
    common.add_argument("--horizon-csv", type=Path, default=None,
                        help="gotowy horizon.csv z klawisza C w newlunar.py zamiast generowania")

    parser = argparse.ArgumentParser(
        description="DTE: kontakt Księżyc–Ziemia z uwzględnieniem terenu (horyzont jak klawisz C "
                    "w newlunar.py) i libracji (model IAU). Wynik: JSON na stdout.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_point = sub.add_parser("point", parents=[common], help="kontakt w jednej chwili")
    p_point.add_argument("--t", required=True, help="czas UTC, ISO 8601 (np. 2026-01-01T00:00:00Z)")
    p_win = sub.add_parser("windows", parents=[common], help="okna kontaktu w przedziale czasu")
    p_win.add_argument("--start", required=True, help="początek, ISO 8601 UTC")
    p_win.add_argument("--end", required=True, help="koniec, ISO 8601 UTC")
    p_win.add_argument("--step-hours", type=int, default=1, help="krok próbkowania [h] (domyślnie 1)")
    args = parser.parse_args(argv)

    opts = dict(antenna_height_m=args.antenna_height_m, min_elevation_deg=args.min_elevation_deg,
                horizon_csv=args.horizon_csv)
    try:
        if args.cmd == "point":
            result = dte_point(parse_utc(args.t), args.lat, args.lon, **opts)
        else:
            result = dte_windows(parse_utc(args.start), parse_utc(args.end), args.lat, args.lon,
                                 step_hours=args.step_hours, **opts)
    except (ValueError, RuntimeError) as e:
        print(f"błąd: {e}", file=sys.stderr)
        return 2
    for warning in result["warnings"]:
        print(f"ostrzeżenie: {warning}", file=sys.stderr)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
