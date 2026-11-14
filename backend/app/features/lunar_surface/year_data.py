"""Roczne dane ``coords/<rok>.csv`` w kształcie ``newlunar.load_year_data``.

``newlunar.load_year_data`` czyta ``coords/{year}.csv`` względem bieżącego katalogu
(``newlunar.py:1458``), a backend działa z innego cwd i z katalogiem coords z ``Settings``.
Wynik (klucze, jednostki, autodetekcja m/km/AU z ``newlunar.py:1470-1474``) jest identyczny.
"""

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Tuple

import numpy as np


@lru_cache(maxsize=4)
def load_year(coords_dir: Path, year: int, j2000: datetime) -> dict:
    path = Path(coords_dir) / f"{year}.csv"
    times = [datetime.strptime(row.split(",", 1)[0], "%Y-%m-%d %H:%M:%S")
             for row in path.read_text(encoding="utf-8").splitlines()[1:] if row]
    coords = np.loadtxt(path, delimiter=",", skiprows=1, usecols=range(1, 7), ndmin=2, dtype=np.float64)
    moon_dist_med = float(np.median(np.linalg.norm(coords[:, 3:6], axis=1)))
    if moon_dist_med > 1e7:
        coords /= 1000.0
    elif moon_dist_med < 1.0:
        coords *= 149597870.7
    d_j2000_total = np.array([(t - j2000).total_seconds() / 86400.0 for t in times], dtype=np.float64)
    return {"times": times, "coords": coords, "d_j2000_total": d_j2000_total}


def time_index(t: datetime) -> Tuple[int, float]:
    """(rok, ułamkowy indeks godzinowy od 1 stycznia 00:00 UTC) — jak suwak „Czas w roku”."""
    t = t.astimezone(timezone.utc).replace(tzinfo=None)
    start = datetime(t.year, 1, 1)
    return t.year, (t - start) / timedelta(hours=1)
