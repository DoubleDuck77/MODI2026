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

import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

REPO_DIR = Path(__file__).resolve().parent

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
