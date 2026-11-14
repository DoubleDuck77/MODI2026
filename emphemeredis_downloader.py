import csv
import re
import time
from datetime import datetime
import requests

# Konfiguracja
API_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
OUTPUT_FILE = "coords.csv"
START_YEAR = 2000
END_YEAR = 2100
STEP_SIZE = "1h"  # Krok czasowy: '1h' (godzina), '1d' (dzień), '10m' (10 minut)
CHUNK_YEARS = 5  # Pobieranie po 5 lat na raz, aby nie przekroczyć limitów API


def fetch_vectors(body_id: str, start_time: str, stop_time: str, step: str) -> dict[str, tuple[str, str, str]]:
    """
    Pobiera wektory położenia (X, Y, Z) w układzie ekliptycznym geocentrycznym z JPL Horizons.

    body_id: '10' dla Słońca, '301' dla Księżyca
    """
    params = {
        "format": "text",
        "COMMAND": f"'{body_id}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'VECTORS'",
        "CENTER": "'500@399'",  # Obserwator geocentryczny (centrum Ziemi)
        "REF_PLANE": "'ECLIPTIC'",  # Płaszczyzna ekliptyki (Oś X -> punkt Barana, Oś Z -> biegun północny ekliptyki)
        "REF_SYSTEM": "'ICRF'",  # Układ odniesienia J2000
        "VEC_TABLE": "'1'",  # Tylko wektory położenia (X, Y, Z)
        "OUT_UNITS": "'KM-S'",  # Jednostki: kilometry (zmień na 'AU-D' dla jednostek astronomicznych)
        "CSV_FORMAT": "'YES'",  # Format wyjściowy łatwy do parsowania
        "START_TIME": f"'{start_time}'",
        "STOP_TIME": f"'{stop_time}'",
        "STEP_SIZE": f"'{step}'",
    }

    response = requests.get(API_URL, params=params, timeout=60)
    response.raise_for_status()
    text = response.text

    # Wyciągnięcie danych między znacznikami $$SOE (Start of Ephemeris) i $$EOE (End of Ephemeris)
    match = re.search(r"\$\$SOE\s*(.*?)\s*\$\$EOE", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"Nie znaleziono danych efemeryd w odpowiedzi API. Fragment odpowiedzi:\n{text[:500]}")

    raw_lines = match.group(1).strip().splitlines()
    ephemeris_data = {}

    for line in raw_lines:
        parts = [p.strip() for p in line.split(",")]
        # Format linii w VEC_TABLE='1' z CSV_FORMAT='YES':
        # JDTDB, Calendar Date (TDB), X, Y, Z,
        if len(parts) >= 5:
            # Oczyszczenie daty (np. 'A.D. 2000-Jan-01 00:00:00.0000' -> '2000-01-01 00:00:00')
            raw_date = parts[1].replace("A.D. ", "").split(".")[0]
            dt = datetime.strptime(raw_date, "%Y-%b-%d %H:%M:%S")
            iso_time = dt.strftime("%Y-%m-%d %H:%M:%S")

            x, y, z = parts[2], parts[3], parts[4]
            ephemeris_data[iso_time] = (x, y, z)

    return ephemeris_data


def main() -> None:
    print(f"Rozpoczynam pobieranie danych ({START_YEAR} - {END_YEAR}, krok: {STEP_SIZE})...")

    with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["time", "sun_x", "sun_y", "sun_z", "moon_x", "moon_y", "moon_z"])

        for year in range(START_YEAR, END_YEAR, CHUNK_YEARS):
            chunk_start = f"{year}-01-01 00:00"
            next_year = min(year + CHUNK_YEARS, END_YEAR)
            chunk_stop = f"{next_year}-01-01 00:00"

            print(f"Pobieranie przedziału: {chunk_start} -> {chunk_stop}...")

            # Pobieranie danych dla Słońca (ID: 10) i Księżyca (ID: 301)
            sun_data = fetch_vectors("10", chunk_start, chunk_stop, STEP_SIZE)
            time.sleep(0.5)  # Krótka pauza, aby nie obciążać serwerów NASA
            moon_data = fetch_vectors("301", chunk_start, chunk_stop, STEP_SIZE)

            # Zapisywanie wierszy (pomijamy ostatni punkt przedziału, jeśli nie jest to rok 2100, aby uniknąć duplikatów na styku paczek)
            timestamps = sorted(sun_data.keys())
            if next_year < END_YEAR and timestamps:
                timestamps.pop()

            for ts in timestamps:
                if ts in moon_data:
                    sx, sy, sz = sun_data[ts]
                    mx, my, mz = moon_data[ts]
                    writer.writerow([ts, sx, sy, sz, mx, my, mz])

            time.sleep(0.5)

    print(f"Zakończono pomyślnie! Dane zapisano w pliku: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
