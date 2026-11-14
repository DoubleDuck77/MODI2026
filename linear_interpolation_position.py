import csv
from datetime import datetime, timedelta
from pathlib import Path


def _szukaj_w_pliku(sciezka: Path, szukane_czasy: set[str]) -> dict[str, list[float]]:
    """Wyszukuje w pliku CSV rekordy dla podanych znaczników czasu."""
    if not sciezka.exists():
        raise FileNotFoundError(f"Brak pliku: {sciezka}")

    znalezione: dict[str, list[float]] = {}
    with open(sciezka, mode="r", encoding="utf-8", newline="") as plik:
        reader = csv.reader(plik)
        next(reader)  # pominięcie nagłówka: time,sun_x,sun_y,sun_z,moon_x,moon_y,moon_z
        for wiersz in reader:
            if wiersz[0] in szukane_czasy:
                znalezione[wiersz[0]] = [float(x) for x in wiersz[1:]]
                if len(znalezione) == len(szukane_czasy):
                    break

    brakujace = szukane_czasy - znalezione.keys()
    if brakujace:
        raise ValueError(f"Nie znaleziono rekordów {sorted(brakujace)} w pliku {sciezka}")

    return znalezione


def interpoluj_polozenie(data_str: str, folder: str = "coords") -> list:
    """
    Dla daty 'YYYY-MM-DD HH:MM' znajduje dwa najbliższe rekordy godzinowe
    obejmujące tę datę (np. 15:00 i 16:00), wykonuje interpolację liniową
    i zwraca 7-elementową listę zgodną z kolumnami pliku CSV.
    """
    dt = datetime.strptime(data_str.strip(), "%Y-%m-%d %H:%M")

    # Dwa sąsiednie punkty godzinowe obejmujące szukaną datę
    t1 = dt.replace(minute=0, second=0, microsecond=0)
    t2 = t1 + timedelta(hours=1)

    t1_str = t1.strftime("%Y-%m-%d %H:%M:%S")
    t2_str = t2.strftime("%Y-%m-%d %H:%M:%S")

    # Gdy podano pełną godzinę (minuty == 00), wystarczy bezpośredni odczyt t1
    if dt == t1:
        dane = _szukaj_w_pliku(Path(folder) / f"{t1.year}.csv", {t1_str})
        return [dt.strftime("%Y-%m-%d %H:%M:%S"), *dane[t1_str]]

    # Jeśli oba rekordy są w tym samym roku — jeden odczyt pliku; na przełomie roku — dwa pliki
    if t1.year == t2.year:
        dane = _szukaj_w_pliku(Path(folder) / f"{t1.year}.csv", {t1_str, t2_str})
        rekord_1, rekord_2 = dane[t1_str], dane[t2_str]
    else:
        rekord_1 = _szukaj_w_pliku(Path(folder) / f"{t1.year}.csv", {t1_str})[t1_str]
        rekord_2 = _szukaj_w_pliku(Path(folder) / f"{t2.year}.csv", {t2_str})[t2_str]

    # Interpolacja liniowa dla wszystkich 6 składowych położenia
    waga = (dt - t1) / (t2 - t1)
    interpolowane = [
        v1 + waga * (v2 - v1)
        for v1, v2 in zip(rekord_1, rekord_2)
    ]

    return [dt.strftime("%Y-%m-%d %H:%M:%S"), *interpolowane]


