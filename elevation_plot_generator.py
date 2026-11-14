import csv
import math
import re
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
DATA_POCZATEK = "2016-01-01 15:34"   # Format: "YYYY-MM-DD HH:MM" (czas lokalny dla KRAJ / REGION)
DATA_KONIEC = "2025-01-01 17:15"     # Format: "YYYY-MM-DD HH:MM" (czas lokalny dla KRAJ / REGION)

KRAJ = "Japonia"                      # Nazwa kraju zgodna z time_zone_converter.py
REGION = None                        # Region/stan dla krajów wielostrefowych (np. "Kalifornia"), w przeciwnym razie None

# Współrzędne obserwatora na Księżycu (domyślnie: Krater Tycho; np. Biegun S: -89.60, 0.00)
LAT_DEG = 89
LON_DEG = -11.36
FOLDER_DANYCH = "coords"

# --- STAŁE ASTRONOMICZNE ---
R_MOON = 1737.4                  # Średni promień Księżyca [km]
R_EARTH = 6371.0                 # Średni promień Ziemi [km]
I_MOON = math.radians(1.5424)    # Nachylenie równika księżycowego do ekliptyki
J2000 = datetime(2000, 1, 1, 12, 0, 0)


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


def oblicz_katy_elewacji(
    dt_utc: datetime,
    wiersz_6: list[float],
    lat_deg: float,
    lon_deg: float,
) -> tuple[float, float]:
    """
    Oblicza dla obserwatora na powierzchni Księżyca (lat_deg, lon_deg):
    1) kąt elewacji Słońca [°] od matematycznego horyzontu,
    2) kąt elewacji dolnej krawędzi Ziemi (R_EARTH = 6371 km) [°] od matematycznego horyzontu.
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

    obs_body = R_MOON * up

    # 1. Kąt elewacji Słońca
    vec_sun = sun_body - obs_body
    dist_sun = float(np.linalg.norm(vec_sun))
    sin_alt_sun = max(-1.0, min(1.0, float(np.dot(vec_sun, up)) / dist_sun))
    elewacja_slonca_deg = math.degrees(math.asin(sin_alt_sun))

    # 2. Kąt elewacji dolnej krawędzi Ziemi
    vec_earth = earth_body - obs_body
    dist_earth = float(np.linalg.norm(vec_earth))
    sin_alt_earth_center = max(-1.0, min(1.0, float(np.dot(vec_earth, up)) / dist_earth))
    alt_earth_center_rad = math.asin(sin_alt_earth_center)
    promien_katowy_ziemi_rad = math.asin(min(1.0, R_EARTH / dist_earth))
    elewacja_dolnej_krawedzi_ziemi_deg = math.degrees(alt_earth_center_rad - promien_katowy_ziemi_rad)

    return elewacja_slonca_deg, elewacja_dolnej_krawedzi_ziemi_deg


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


def generuj_tablice_elewacji(
    data_poczatek_lokalna: str,
    data_koniec_lokalna: str,
    kraj: str = KRAJ,
    region: str | None = REGION,
    lat_deg: float = LAT_DEG,
    lon_deg: float = LON_DEG,
    folder: str = FOLDER_DANYCH,
) -> list[list]:
    """
    Przelicza przedział czasu podany w strefie czasowej wybranego kraju i regionu na UTC,
    oblicza kąty elewacji z danych w folderze `coords`, a następnie zwraca 3-kolumnową tablicę
    z czasem w lokalnej strefie czasowej:
    [[data_i_godzina_lokalna_str, kat_elewacji_slonca_deg, kat_elewacji_dolnej_krawedzi_ziemi_deg], ...]
    """
    strefa_iana = define_IANA_zone(kraj, region)
    if strefa_iana.startswith("Błąd"):
        raise ValueError(f"{strefa_iana} dla kraju '{kraj}'.")

    data_poczatek_utc = convert_to_utc(data_poczatek_lokalna, strefa_iana)
    data_koniec_utc = convert_to_utc(data_koniec_lokalna, strefa_iana)

    punkty_czasu_utc = generuj_punkty_czasowe(data_poczatek_utc, data_koniec_utc)

    lata_pelnych_godzin = sorted({dt.year for dt in punkty_czasu_utc if dt.minute == 0 and dt.second == 0})
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
    for dt_utc in punkty_czasu_utc:
        if dt_utc.minute == 0 and dt_utc.second == 0:
            klucz = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
            if klucz not in dane_godzinowe:
                raise ValueError(f"Nie znaleziono rekordu {klucz} w folderze '{folder}'.")
            wiersz_6 = dane_godzinowe[klucz]
        else:
            interp = interpoluj_polozenie(dt_utc.strftime("%Y-%m-%d %H:%M"), folder=folder)
            wiersz_6 = [float(x) for x in interp[1:7]]

        kat_slonca, kat_ziemi_dol = oblicz_katy_elewacji(dt_utc, wiersz_6, lat_deg, lon_deg)
        czas_lokalny_str = convert_time_zone(dt_utc.strftime("%Y-%m-%d %H:%M"), strefa_iana)
        tablica.append([czas_lokalny_str, kat_slonca, kat_ziemi_dol])

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
    tablica: list[list],
    lat_deg: float,
    lon_deg: float,
    strefa_iana: str,
) -> None:
    """Wizualizuje przebieg kąta elewacji Słońca oraz dolnej krawędzi Ziemi w matplotlib."""
    daty = [datetime.strptime(wiersz[0], "%Y-%m-%d %H:%M") for wiersz in tablica]
    elewacje_slonca = [wiersz[1] for wiersz in tablica]
    elewacje_ziemi = [wiersz[2] for wiersz in tablica]
    strefa_utc = _formatuj_strefe_utc(strefa_iana, daty)

    # --- Wykres 1: Kąt elewacji Słońca ---
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(daty, elewacje_slonca, color="#f59e0b", linewidth=1.8, label="Elewacja Słońca [°]")
    ax1.axhline(0.0, color="#0284c7", linestyle="--", linewidth=1.2, label="Horyzont matematyczny (0°)")

    ax1.fill_between(
        daty, elewacje_slonca, 0.0,
        where=[e >= 0.0 for e in elewacje_slonca],
        color="#fde047", alpha=0.25, interpolate=True, label="Dzień księżycowy (> 0°)"
    )
    ax1.fill_between(
        daty, elewacje_slonca, 0.0,
        where=[e < 0.0 for e in elewacje_slonca],
        color="#1e3a8a", alpha=0.18, interpolate=True, label="Noc księżycowa (< 0°)"
    )

    if len(daty) > 1:
        ax1.set_xlim(daty[0], daty[-1])

    ax1.set_title(
        f"Kąt elewacji Słońca od matematycznego horyzontu na Księżycu "
        f"(Lat: {lat_deg:+.2f}°, Lon: {lon_deg:+.2f}° | {strefa_utc})"
    )
    ax1.set_xlabel(f"Data i godzina ({strefa_utc})")
    ax1.set_ylabel("Kąt elewacji [°]")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="best")
    fig1.autofmt_xdate()
    fig1.tight_layout()

    # --- Wykres 2: Kąt elewacji dolnej krawędzi Ziemi ---
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    ax2.plot(daty, elewacje_ziemi, color="#2563eb", linewidth=1.8, label="Elewacja dolnej krawędzi Ziemi [°]")
    ax2.axhline(0.0, color="#0284c7", linestyle="--", linewidth=1.2, label="Horyzont matematyczny (0°)")

    ax2.fill_between(
        daty, elewacje_ziemi, 0.0,
        where=[e >= 0.0 for e in elewacje_ziemi],
        color="#38bdf8", alpha=0.25, interpolate=True, label="Cała tarcza Ziemi nad horyzontem (> 0°)"
    )
    ax2.fill_between(
        daty, elewacje_ziemi, 0.0,
        where=[e < 0.0 for e in elewacje_ziemi],
        color="#1e293b", alpha=0.18, interpolate=True, label="Dolna krawędź Ziemi poniżej horyzontu (< 0°)"
    )

    if len(daty) > 1:
        ax2.set_xlim(daty[0], daty[-1])

    ax2.set_title(
        f"Kąt elewacji dolnej krawędzi Ziemi (R = 6371 km) od matematycznego horyzontu na Księżycu "
        f"(Lat: {lat_deg:+.2f}°, Lon: {lon_deg:+.2f}° | {strefa_utc})"
    )
    ax2.set_xlabel(f"Data i godzina ({strefa_utc})")
    ax2.set_ylabel("Kąt elewacji [°]")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="best")
    fig2.autofmt_xdate()
    fig2.tight_layout()

    plt.show()


if __name__ == "__main__":
    strefa = define_IANA_zone(KRAJ, REGION)
    wynik = generuj_tablice_elewacji(
        DATA_POCZATEK,
        DATA_KONIEC,
        kraj=KRAJ,
        region=REGION,
        lat_deg=LAT_DEG,
        lon_deg=LON_DEG,
        folder=FOLDER_DANYCH,
    )
    rysuj_wykresy_elewacji(wynik, LAT_DEG, LON_DEG, strefa)
