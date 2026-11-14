# DTE (Direct-to-Earth) — linia wzroku Ziemia–Księżyc: plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Aktualizacja po `f4ca9e2` („updates2newlunar”).** Część opisu `newlunar.py` niżej jest historyczna:
> - `newlunar.py` pobiera teraz działający DEM z NASA SVS (`ldem_3_8bit.jpg`) do `Textures/moon_dem.npy` (1024×512, 8 bitów, ~10.7 km/px). Nie wpada w proceduralny fallback i nie czyta już `moon_dem_v2.npy`.
> - API: `update_observer(lat, lon, eye_height_m=2.0)`. Klawisz C zapisuje `horizon.csv` w 10 kolumnach (`Azimuth_deg,Horizon_Altitude_deg,…,Observer_*`), 480 wierszy co 0.75°.
> - DTE dalej podaje kodowi `newlunar` własny, dokładniejszy LOLA LDEM_16 (`moon_dem_v2.npy`, z niego korzysta też `lunar_stellarium.py`) i zapisuje horyzont funkcją `export_horizon_csv`, czyli tą samą co klawisz C. `load_horizon_csv` czyta oba formaty. Gotowy plik z klawisza C podany dla innego punktu albo innej wysokości anteny daje błąd.

**Cel:** Jeden samodzielny plik `dte_line_of_sight.py` w katalogu głównym, tak jak inne skrypty w repo. Dla punktu na Księżycu i chwili UTC zwraca bool „jest kontakt z Ziemią” (DTE). Horyzont terenowy pochodzi z pliku `horizon.csv` liczonego **dokładnie tak jak klawisz C w `newlunar.py`**, ale automatycznie, bez okna i bez klikania. Pozycję Ziemi z libracją liczymy sami. Moduł liczy też okna kontaktu w przedziale czasu i wypisuje wynik jako JSON z CLI.

**Architektura:** Moduł ma cztery sekcje.
- **Efemeryda i orientacja:** `coords/*.csv` + model IAU → wektor Ziemi w układzie Księżyca.
- **Teren:** prawdziwy LOLA DEM zapisany w cache, który czyta `newlunar.py`. Horyzont liczy `newlunar.LunarTerrain3D.update_observer`, a zapis idzie do CSV w formacie klawisza C.
- **Widoczność:** kontakt, ułamek tarczy, okna.
- **CLI.**

`newlunar.py` tylko importujemy, nigdy nie modyfikujemy. Pola wyniku mają nazwy z kontraktu `LineOfSight`/`VisibilityWindows` (`backend/app/features/line_of_sight/contract.py`), żeby późniejsze łączenie w stronę było cienką fasadą.

**Tech stack:** Python ≥ 3.10, numpy, stdlib (argparse, json, urllib), import `newlunar.py`.

**Spec:** Nie ma osobnego dokumentu. Wymagania pochodzą z prośby użytkownika:
- pkt 2: „Wykrywanie linii wzroku Ziemia–Księżyc (DTE) z uwzględnieniem topografii terenu oraz libracji Księżyca (bool czy jest kontakt)”;
- „nie możesz dotykać new_lunar.py”;
- „na razie po prostu osobnym modułem jak wszystkie pliki tutaj, później będziemy to łączyć”;
- decyzja: „horyzont biorę wyłącznie z pliku horizon.csv wygenerowanego klawiszem C, a pozycję Ziemi liczę sam … tylko nie ręcznie klikając, tak samo ma działać automatycznie”.

Konwencje pochodzą z `docs/ARCHITECTURE.md`.

## Kontekst

`newlunar.py` jest na `origin/main` (commit `8ad9154`, „generator horizon.csv pod C”), a lokalny `main` jest 3 commity w tyle. Plik to nowy `lunar_stellarium.py` plus eksport horyzontu pod klawiszem C (`newlunar.py:1149-1160`):
- format: `Azimuth_deg,Altitude_deg`, 720 wierszy co 0.5°, 4 miejsca po przecinku;
- liczy go `LunarTerrain3D.update_observer(lat, lon, alt_km)`, który robi ray-march po DEM z krzywizną i wygładza wynik `[0.25, 0.5, 0.25]`;
- plik **nie zapisuje lat/lon ani czasu**.

**Odkrycie, które zmienia sens danych z `newlunar.py`:** oba adresy DEM (`LOLA_DEM_URLS`) i adres tekstury (`LRO_COLOR_URLS`) zwracają dziś **404** (sprawdzone curlem i przez API Commons: plik nie istnieje). Cache `Textures/moon_dem_v2.npy` nie istnieje, więc `newlunar.py` po cichu używa `generate_fallback_lunar_dem()`, czyli **proceduralnego, zmyślonego terenu** (losowe kratery z `seed=42`). HUD pokazuje wtedy „DEM: Proceduralny DEM”. `horizon.csv` z klawisza C jest dziś liczony na fikcyjnym terenie. To samo dotyczy `lunar_stellarium.py`.

**Rozwiązanie bez dotykania `newlunar.py`:** `load_or_download_lunar_maps` najpierw czyta `Textures/moon_dem_v2.npy` (`newlunar.py:160-162`). Nasz moduł zapisze tam prawdziwy LOLA w formacie, którego oczekuje `newlunar.py`:
- tablica float32 [km względem 1737.4];
- wiersz 0 to lat +90, kolumna 0 to lon −180.

Od tej chwili klawisz C, `newlunar.py` i nasz automatyczny generator liczą horyzont na prawdziwym terenie i dają identyczne wyniki.

**Odpowiedź na pytanie „skąd bierze się JSON”:**
- `newlunar.py` nie czyta JSON-a. Korzysta z:
  - `coords/<rok>.csv`: JPL Horizons przez `emphemeredis_downloader.py`, geocentryczne wektory w ekliptyce J2000, w **metrach**, co godzinę, etykiety TDB;
  - DEM (jak wyżej, dziś proceduralny);
  - tekstur.
- JSON dla strony to kontrakt `line_of_sight.point`/`windows`. Dziś to statyczny przykład z `contracts/examples/` zwracany przez stub `LineOfSightFacade`. Ten moduł dostarcza prawdziwe liczby, które później go wypełnią.

## Decyzje projektowe

- **Horyzont:** generujemy go kodem `newlunar.py`, a nie własnym. `import newlunar` bez okna; gdy brak `pygame`, przed importem podstawiamy pusty moduł `pygame` (sprawdzone: import 0.1 s, `update_observer` 0.06 s). Dla `(lat, lon, antena)` zapisujemy `horizons/horizon_lat{lat:+.4f}_lon{lon:+.4f}_h{h:g}m.csv` w formacie identycznym z klawiszem C, a DTE czyta horyzont **wyłącznie z tego pliku**. `--horizon-csv PATH` pozwala zamiast tego podać plik zapisany ręcznie klawiszem C.
- **DEM:** LOLA LDEM_16 z PDS. Format: 5760×2880 int16 LE, 0.5 m/DN, 16 px/°, kolumna 0 = lon 0°E, środki pikseli. Konwertujemy go do formatu `newlunar.py` (`np.roll` o 2880 kolumn, /1000 → km, float32) i zapisujemy do `Textures/moon_dem_v2.npy` (~66 MB, w `.gitignore`). Przesunięcie o pół piksela (~1 km) jest pomijalne. Surowy `.img` po konwersji usuwamy. Jeśli cache już istnieje, używamy go bez zmian.
- **Pozycja Ziemi i libracja:** model obrotu Księżyca IAU (Archinal i in. 2011). Zawiera librację fizyczną i daje układ Mean-Earth, zgodny z LOLA. Zmierzono na 2026 r.: punkt podziemski ma lat [−6.79°, +6.86°] i lon [−7.93°, +7.59°]. Macierz Cassiniego w `newlunar.py` różni się w 2026 r. o 0.37–0.40° (precesja), więc **bool może się różnić od napisu w HUD `newlunar.py` tylko wtedy, gdy Ziemia jest w odległości ~0.4° od horyzontu**.
- **Kontakt:** `dte_contact = clearance_deg > min_elevation_deg`, gdzie `clearance_deg = alt środka Ziemi − horyzont z CSV w azymucie Ziemi`, a domyślny `min_elevation_deg` to 0. Osobno liczone jest `earth_visible = visible_disk_fraction > 0` (semantyka kontraktu).

## Global Constraints

- Nie modyfikujemy `newlunar.py`. Wolno go tylko importować i zapisywać cache danych, który sam czyta (`Textures/moon_dem_v2.npy`).
- Całość mieści się w jednym pliku `dte_line_of_sight.py` w katalogu głównym, bez integracji z backendem i frontem.
- Import modułu niczego nie wypisuje, nie pobiera i nie importuje `newlunar`. Wszystko dzieje się leniwie, przy pierwszym użyciu.
- Nie piszemy testów automatycznych ani TDD. Weryfikujemy wyłącznie uruchomieniem (memory `no-tdd-smoke-verify-only`).
- Zależności to numpy, stdlib i `newlunar.py`. `pygame` nie jest wymagany (stub tylko wtedy, gdy `import pygame` się nie uda).
- Kod musi działać na Pythonie 3.10 (lokalnie 3.10.12) i 3.12. Na 3.10 trzeba ręcznie obsłużyć sufiks `Z` w `fromisoformat`. Nie używamy `datetime.UTC`.
- Konwencje z `docs/ARCHITECTURE.md`:
  - czas to UTC ISO 8601 z `Z`, zakres 2000-01-01T00:00Z … 2100-01-01T00:00Z;
  - azymut od N zgodnie z ruchem wskazówek (taki sam jak w `newlunar`), długość wschodnia dodatnia, lon ∈ [−180, 180];
  - jednostki w nazwach pól.
- `coords/*.csv` są w metrach, więc dzielimy przez 1000. Etykiety TDB traktujemy jak UTC.
- Ścieżki liczymy względem `<repo> = Path(__file__).resolve().parent`: `<repo>/coords` (nadpisywane przez `MODI_COORDS_DIR`), `<repo>/Textures`, `<repo>/horizons`. Konstrukcję `LunarTerrain3D` robimy z cwd = `<repo>`, bo zapisuje `Textures/regolith_detail_512.npz` względem cwd. Cwd przywracamy w `finally`.
- Stałe: `R_MOON_KM = 1737.4`, `R_EARTH_KM = 6371.0`, `OBLIQUITY_J2000_DEG = 23.4392911`.
- Pracujemy na gałęzi `feat/dte-line-of-sight`. Każdy commit kończy się linią `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Bez push.

## Review Focus

1. **Czas z `Z` lub offsetem na Pythonie 3.10.** Wszystkie formy dają tę samą chwilę UTC. Sprawdzenie w Task 1.
2. **Przełom roku i ostatnia godzina danych.** Okno przez północ 31.12, `t=2100-01-01T00:00Z` działa, a `00:30Z` daje exit 2 z „poza zakresem”. Sprawdzenie w Task 3.
3. **Szew lon ±180 i bieguny.** Horyzont dla lon −180 i +180 jest identyczny, a Shackleton (−89.6, 0) daje skończone wartości. Sprawdzenie w Task 2.
4. **Ziemia muskająca horyzont.** `visible_disk_fraction` ∈ (0, 1), granice okien są spójne z próbkami, a azymut Ziemi blisko 0°/360° poprawnie interpoluje się po okresie. Sprawdzenie w Task 3.
5. **Urwane pobieranie DEM albo zły plik `--horizon-csv`** (zły nagłówek, nie 720 wierszy). Ma być czytelny komunikat zamiast cichego złego wyniku. Sprawdzenie w Task 2.

---

### Task 1: Synchronizacja + efemeryda i orientacja Księżyca (libracja)

**Files:**
- Create: `dte_line_of_sight.py` (docstring, stałe, sekcja „EFEMERYDA I ORIENTACJA”)
- Create: `docs/superpowers/plans/2026-11-14-dte-line-of-sight.md` (kopia planu)

**Interfaces:**
- Produces:
  - `R_MOON_KM`, `R_EARTH_KM`, `DATA_START`, `DATA_END` (aware UTC)
  - `parse_utc(s: str) -> datetime`: aware UTC. Akceptuje `Z`, offset i czas bez strefy. Poza zakresem rzuca `ValueError("czas … poza zakresem danych …")`.
  - `class Ephemeris(coords_dir: Path | None = None)` z metodą `.moon_geo_km(times: Sequence[datetime]) -> np.ndarray (N,3)`. Interpoluje liniowo między godzinami i skleja lata przez offset godzin od 2000-01-01. Pliki są ciągłe, a `2100.csv` ma 1 wiersz. Lata cache'uje.
  - `moon_me_matrix(d: np.ndarray) -> np.ndarray (N,3,3)`: ekliptyka J2000 → Księżyc ME. `d` to doby od 2000-01-01T12:00.
  - `earth_in_moon_frame_km(eph, times) -> np.ndarray (N,3)`.

- [ ] **Step 1:** `git pull --ff-only origin main && git checkout -b feat/dte-line-of-sight`. Oczekiwane: fast-forward do `8ad9154`, a `newlunar.py` istnieje. Skopiuj plan do `docs/superpowers/plans/2026-11-14-dte-line-of-sight.md`.
- [ ] **Step 2:** Zaimplementuj `parse_utc` (końcowe `Z` → `+00:00`) i `Ephemeris` (`np.loadtxt(..., delimiter=",", skiprows=1, usecols=range(1,7), ndmin=2) / 1000.0`, jak `orbital.py:382`).
- [ ] **Step 3:** Zaimplementuj `moon_me_matrix` (IAU, Archinal 2011).
  `T = d/36525`, kąty w stopniach. Rotacje układu: `Rz(a)=[[c,s,0],[-s,c,0],[0,0,1]]`, `Rx(a)=[[1,0,0],[0,c,s],[0,-s,c]]`.
  ```
  E1=125.045-0.0529921d  E2=250.089-0.1059842d  E3=260.008+13.0120009d  E4=176.625+13.3407154d
  E5=357.529+0.9856003d  E6=311.589+26.4057084d E7=134.963+13.0649930d  E8=276.617+0.3287146d
  E9=34.226+1.7484877d   E10=15.134-0.1589763d  E11=119.743+0.0036096d  E12=239.961+0.1643573d
  E13=25.053+12.9590088d
  α0 = 269.9949+0.0031T-3.8787sinE1-0.1204sinE2+0.0700sinE3-0.0172sinE4+0.0072sinE6-0.0052sinE10+0.0043sinE13
  δ0 = 66.5392+0.0130T+1.5419cosE1+0.0239cosE2-0.0278cosE3+0.0068cosE4-0.0029cosE6+0.0009cosE7+0.0008cosE10-0.0009cosE13
  W  = 38.3213+13.17635815d-1.4e-12d²+3.5610sinE1+0.1208sinE2-0.0642sinE3+0.0158sinE4+0.0252sinE5
       -0.0066sinE6-0.0047sinE7-0.0046sinE8+0.0028sinE9+0.0052sinE10+0.0040sinE11+0.0019sinE12-0.0044sinE13
  M_eq→ME  = Rz(W) · Rx(90°−δ0) · Rz(90°+α0)
  ecl→eq:   x'=x,  y'=cosε·y − sinε·z,  z'=sinε·y + cosε·z   (ε = 23.4392911°)
  moon_me_matrix = M_eq→ME · (ecl→eq);   earth_in_moon_frame_km = moon_me_matrix(d) @ (−moon_geo_km)
  ```
- [ ] **Step 4: Weryfikacja uruchomieniem**
  ```bash
  python3 -c "
  from dte_line_of_sight import *; import numpy as np, math
  e=Ephemeris(); v=earth_in_moon_frame_km(e,[parse_utc('2026-01-01T00:00:00Z')])[0]
  print(round(math.degrees(math.asin(v[2]/np.linalg.norm(v))),3), round(math.degrees(math.atan2(v[1],v[0])),3), round(np.linalg.norm(v),0))
  print(parse_utc('2026-01-01T01:00:00+01:00')==parse_utc('2026-01-01T00:00:00Z')==parse_utc('2026-01-01T00:00:00'))"
  ```
  Oczekiwane wyjście: `-6.555 -1.278 ~361000` (±0.01°) oraz `True`. Import niczego nie wypisuje. `parse_utc('2101-01-01T00:00:00Z')` rzuca `ValueError` z „poza zakresem”.
- [ ] **Step 5: Commit** `feat(dte): ephemeris loader and IAU lunar orientation (libration)`

---

### Task 2: Teren — prawdziwy DEM dla `newlunar` i automatyczny `horizon.csv` (jak klawisz C)

**Files:**
- Modify: `dte_line_of_sight.py` (sekcja „TEREN / HORYZONT”)
- Modify: `.gitignore`: dopisz `Textures/moon_dem_v2.npy`, `Textures/moon_dem.jpg`, `Textures/regolith_detail_*.npz`, `Textures/*.part` i `horizons/`

**Interfaces:**
- Consumes: nic z Task 1.
- Produces:
  - `LDEM16_URL = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/ldem_16.img"`
  - `NEWLUNAR_DEM_CACHE = <repo>/Textures/moon_dem_v2.npy`
  - `ldem16_to_newlunar(raw_path: Path) -> np.ndarray`: sprawdza, czy rozmiar wynosi `5760*2880*2 = 33177600` B. Jeśli nie, rzuca `RuntimeError("niepełny plik <ścieżka> (X B) — usuń go i uruchom ponownie albo pobierz ręcznie z <URL>")`. Konwersja: `np.memmap('<i2', shape=(2880,5760))` → `·0.5/1000` → `np.roll(…, 2880, axis=1)` → float32.
  - `ensure_newlunar_dem() -> np.ndarray`: jeśli cache istnieje, robi `np.load`. W przeciwnym razie pobiera LDEM_16 (urllib, `User-Agent: modi2026-dte`, do `Textures/ldem_16.img.part`, postęp na stderr), wywołuje `ldem16_to_newlunar`, robi `np.save` cache i usuwa surowy plik.
  - `generate_horizon_csv(lat_deg: float, lon_deg: float, antenna_height_m: float = 2.0, out_dir: Path | None = None) -> tuple[Path, float]` zwraca `(ścieżka CSV, wysokość gruntu obserwatora [m])`. Jedna instancja `LunarTerrain3D(ensure_newlunar_dem(), np.zeros((2,2,3), np.float32))` na proces, potem `update_observer(lat, lon, antenna_height_m/1000)`. Zapis **identyczny jak `newlunar.py:1152-1157`**: nagłówek `Azimuth_deg,Altitude_deg`, wiersze `f"{math.degrees(az):.4f}", f"{math.degrees(alt):.4f}"` po `zip(az_grid[:-1], horizon_alt)`. Grunt to `obs_elev_km·1000`.
  - `load_horizon_csv(path: Path) -> tuple[np.ndarray, np.ndarray]` zwraca `(az_deg, alt_deg)`. Waliduje nagłówek `Azimuth_deg,Altitude_deg` i ≥ 2 wiersze, rosnące az w [0, 360). Błędy dają `ValueError` z nazwą pliku.
  - `horizon_at(az_tab, alt_tab, az_deg) -> np.ndarray`: `np.interp(az_deg % 360, az_tab, alt_tab, period=360)`.
  - `_newlunar()` (prywatny): leniwy import. `try: import pygame` / `except ImportError: sys.modules['pygame'] = types.ModuleType('pygame')`, potem `import newlunar`.

- [ ] **Step 1:** Zaimplementuj `ldem16_to_newlunar` i `ensure_newlunar_dem`.
- [ ] **Step 2:** Zaimplementuj `_newlunar`, `generate_horizon_csv` (z cwd = `<repo>` na czas konstrukcji `LunarTerrain3D`), `load_horizon_csv` i `horizon_at`.
- [ ] **Step 3: Weryfikacja uruchomieniem** (pierwsze uruchomienie pobierze ~33 MB)
  ```bash
  python3 -c "
  from dte_line_of_sight import *; import numpy as np
  d=ensure_newlunar_dem(); print(d.shape, d.dtype, round(float(d.min()),2), round(float(d.max()),2))
  for n,la,lo in [('Tycho',-43.3,-11.2),('Imbrium',33.0,-16.0),('Shackleton',-89.6,0.0),('Seam-',10.0,-180.0),('Seam+',10.0,180.0)]:
      p,g=generate_horizon_csv(la,lo); az,alt=load_horizon_csv(p); print(n,p.name,len(az),az[0],az[-1],round(alt.max(),2),round(alt.min(),2),round(g,1))"
  head -2 horizons/horizon_lat-43.3000_lon-11.2000_h2m.csv
  ```
  Oczekiwane:
  - `(2880, 5760) float32 ≈-9.1 ≈10.79`;
  - każdy CSV ma 720 wierszy i az od `0.0` do `359.5`;
  - nagłówek to `Azimuth_deg,Altitude_deg`;
  - Tycho: max ≈ 2–7°;
  - Imbrium: max < 1.5°;
  - Shackleton: wartości skończone;
  - `Seam-` i `Seam+` mają identyczne wartości;
  - drugie uruchomienie niczego nie pobiera.

  `newlunar.py` widzi teraz prawdziwy DEM (bez okna):
  ```bash
  python3 -c "import sys,types;sys.modules['pygame']=types.ModuleType('pygame');import newlunar as n;d,a,s=n.load_or_download_lunar_maps();print(s,d.shape)"
  ```
  Oczekiwane: `LOLA DEM (wygładzony) (2880, 5760)`. Ostrzeżenia o 404 tekstury albedo są spodziewane.

  Błędy:
  - `head -c 10 /dev/zero > /tmp/x.img; python3 -c "from dte_line_of_sight import *; from pathlib import Path; ldem16_to_newlunar(Path('/tmp/x.img'))"` daje `RuntimeError` z „niepełny plik”;
  - `printf 'a,b\n1,2\n' > /tmp/bad.csv` z `load_horizon_csv` daje `ValueError` z nazwą pliku.

  Na koniec `git status` nie pokazuje cache, `horizons/` ani `.part`.
- [ ] **Step 4: Commit** `feat(dte): real LOLA DEM cache for newlunar and headless horizon.csv generator`

---

### Task 3: Widoczność, kontakt DTE, okna i CLI

**Files:**
- Modify: `dte_line_of_sight.py` (sekcje „WIDOCZNOŚĆ” i „CLI”, `if __name__ == "__main__": main()`)

**Interfaces:**
- Consumes: `parse_utc`, `Ephemeris`, `earth_in_moon_frame_km`, `R_MOON_KM`, `R_EARTH_KM` (Task 1); `generate_horizon_csv`, `load_horizon_csv`, `horizon_at` (Task 2).
- Produces:
  - `disk_fraction(clearance_deg: float, radius_deg: float) -> float`
  - `dte_point(t: datetime, lat_deg: float, lon_deg: float, *, antenna_height_m=2.0, min_elevation_deg=0.0, horizon_csv: Path | None = None, eph=None) -> dict`
  - `dte_windows(start: datetime, end: datetime, lat_deg: float, lon_deg: float, *, step_hours=1, antenna_height_m=2.0, min_elevation_deg=0.0, horizon_csv: Path | None = None, eph=None) -> dict`
  - `horizon_csv=None` oznacza `generate_horizon_csv(lat, lon, antenna_height_m)`, a podana ścieżka oznacza plik z klawisza C (wtedy grunt = 0, a `observer_elevation_m` = null).
  - Obie funkcje korzystają z jednej wewnętrznej `_evaluate(times, …)`, wektorowo dla N chwil i jednego CSV.
- CLI:
  - `python3 dte_line_of_sight.py point --t ISO --lat F --lon F [--antenna-height-m 2] [--min-elevation-deg 0] [--horizon-csv PATH]`
  - `python3 dte_line_of_sight.py windows --start ISO --end ISO --lat F --lon F [--step-hours 1] [...]`
  - Wynik: `json.dumps(..., indent=2, ensure_ascii=False)`. `ValueError`/`RuntimeError` idą na stderr z exit 2.

- [ ] **Step 1: `_evaluate`.**
  - Baza lokalna jak w `newlunar`: `up=(cosφcosλ, cosφsinλ, sinφ)`, `east=(−sinλ, cosλ, 0)`, `north=up×east`.
  - `r_obs = R_MOON_KM + (grunt_m + antenna_height_m)/1000`.
  - `v = E − r_obs·up`, `alt = asin(v·up/|v|)`, `az = atan2(v·east, v·north) mod 360`, `ρ = asin(R_EARTH_KM/|v|)`.
  - `hor = horizon_at(…, az)`, `clearance = alt − hor`.
  - Libracja to lat/lon kierunku `E`.
  - Walidacja: lat ∈ [−90, 90], lon ∈ [−180, 180], `antenna_height_m ≥ 0`, `step_hours` to int ≥ 1, `start < end`. Naruszenie daje `ValueError`.
- [ ] **Step 2: `disk_fraction`.**
  `x = clamp(clearance/ρ, −1, 1)`; `f = 1 − (acos(x) − x·sqrt(1−x²))/π`.
- [ ] **Step 3: Kształt wyniku `dte_point`.**
  ```
  t ("…Z"), observer{lat_deg,lon_deg}, observer_elevation_m, antenna_height_m,
  earth{alt_deg,az_deg,distance_km}, earth_angular_radius_deg, libration{lat_deg,lon_deg},
  horizon_elevation_deg, clearance_deg, visible_disk_fraction, earth_visible,
  min_elevation_deg, dte_contact, horizon_csv
  ```
  Zaokrąglenia: stopnie do 4 miejsc, km i m do 1 miejsca. `clearance_deg` liczymy z zaokrąglonych alt i horyzontu, bo walidator kontraktu wymaga zgodności do 1e-6. `az_deg` po zaokrągleniu bierzemy `% 360`. `earth_visible = visible_disk_fraction > 0`.
- [ ] **Step 4: `dte_windows`.**
  - Próbki to `t_k = start + k·step ≤ end`.
  - Okno to maksymalny ciąg próbek z `dte_contact`: `start = t_i`, `end = min(t_j + step, end)`. Pomijamy okna o zerowej długości.
  - `max_clearance_deg` to maksimum `clearance` w oknie.
  - `visible_fraction = Σ okien / (end − start)`, 4 miejsca.
  - Wynik: `observer, start, end, step_hours, min_elevation_deg, horizon_csv, samples, windows[{start,end,max_clearance_deg}], visible_fraction`.
- [ ] **Step 5: Weryfikacja uruchomieniem**
  ```bash
  T=2026-01-01T00:00:00Z
  for p in "0 0" "0 180" "0 90" "0 -90" "-89.6 0"; do set -- $p
    python3 dte_line_of_sight.py point --t $T --lat $1 --lon $2 | python3 -c "import sys,json;d=json.load(sys.stdin);print('$p',d['earth'],d['horizon_elevation_deg'],d['visible_disk_fraction'],d['dte_contact'],d['libration'],d['horizon_csv'])"; done
  ```
  Oczekiwane:
  - `0 0`: alt ≈ 83.3, az ≈ 191.0, ≈ 359300 km, `dte_contact` true;
  - `0 180`: alt ≈ −83.3, `dte_contact` false, `earth_visible` false;
  - `0 90`: alt ≈ −1.55, `dte_contact` false;
  - `0 -90`: alt ≈ +0.99, wynik zależy od terenu;
  - `-89.6 0`: alt ≈ +6.7;
  - wszędzie libracja ≈ (−6.555, −1.278);
  - `horizon_csv` wskazuje plik w `horizons/`.

  ```bash
  for p in "0 0" "0 180" "0 90" "-89.6 0"; do set -- $p
    python3 dte_line_of_sight.py windows --start 2026-01-01T00:00:00Z --end 2026-02-01T00:00:00Z --lat $1 --lon $2 | python3 -c "import sys,json;d=json.load(sys.stdin);print('$p',len(d['windows']),d['visible_fraction'])"; done
  ```
  Oczekiwane: `0 0` → 1 okno i 1.0; `0 180` → 0 okien i 0.0; `0 90` oraz `-89.6 0` → ≥ 1 okno i ułamek w (0, 1).

  Przypadki brzegowe:
  - windows `2026-12-31T20:00:00Z`…`2027-01-01T04:00:00Z` dla `0 0` daje 9 próbek, 1 okno i 1.0;
  - point `--t 2100-01-01T00:00:00Z` daje JSON;
  - point `--t 2100-01-01T00:30:00Z` daje exit 2 i „poza zakresem”;
  - `disk_fraction` dla `(0,1) (1,1) (-1,1) (5,1) (-5,1)` daje `0.5 1.0 0.0 1.0 0.0`;
  - `point` w chwili `start` dowolnego okna dla `0 90` daje |`clearance_deg`| < kilka dziesiątych stopnia, a ułamek tarczy mieści się w (0, 1);
  - `horizon_at(np.array([0.,359.5]), np.array([1.,3.]), np.array([359.75]))` daje 2.0 (interpolacja przez 360°).

  Tryb pliku z klawisza C:
  ```bash
  python3 -c "print('Azimuth_deg,Altitude_deg');[print(f'{a/2:.4f},10.0000') for a in range(720)]" > /tmp/h10.csv
  ```
  Następnie `windows` dla `0 90` z `--horizon-csv /tmp/h10.csv` daje 0 okien i 0.0, a `observer_elevation_m` w `point` jest `null`.

  Kontrakt (backend ma pydantic):
  ```bash
  cd backend && python3 -c "import json,subprocess as s;from app.features.line_of_sight.contract import LineOfSight as L;d=json.loads(s.check_output(['python3','dte_line_of_sight.py','point','--t','2026-01-01T00:00:00Z','--lat','0','--lon','0'],cwd='..'));k={x:d[x] for x in ['t','observer','earth','horizon_elevation_deg','clearance_deg','visible_disk_fraction','earth_visible']};k['meta']={'feature':'line_of_sight','endpoint':'point','contract_version':'0.1.0','source':'computed'};print(L.model_validate(k).earth_visible)"
  ```
  Oczekiwane: `True`.
- [ ] **Step 6: Commit** `feat(dte): Direct-to-Earth contact, visibility windows and CLI`

---

### Task 4: Sąsiednie poprawki w `lunar_stellarium.py` (memory `fix-adjacent-bugs-in-scope`)

**Dowody** (plik zmieniony w `a24c812` „nowy lunar stellarium”):
- `lunar_stellarium.py:797` czyta `f"Coords/{year}.csv"` (wielkie C). To regresja poprawki `466e2b4`: na Linuksie program przechodzi na dane testowe. Konwersja m→km już jest (`coords *= 0.001` przy |moon| > 1e7).
- `lunar_stellarium.py:221` szuka `Textures/earth_night8K.jpg`, a w repo jest `Textures/earrth_night8K.jpg`.
- Martwe URL-e DEM naprawia bez zmian w kodzie cache z Task 2, bo ścieżka cache jest ta sama.

**Files:** Modify `lunar_stellarium.py:797`, `lunar_stellarium.py:221`

- [ ] **Step 1:** Zmień `"Coords/"` na `"coords/"`. Na początek listy kandydatów nocnej tekstury dopisz `"Textures/earrth_night8K.jpg"`.
- [ ] **Step 2: Weryfikacja uruchomieniem:**
  ```bash
  python3 -c "import sys,types;sys.modules['pygame']=types.ModuleType('pygame');import lunar_stellarium as L,numpy as np;d=L.load_year_data(2026);print(np.linalg.norm(d['coords'][0,3:6]))"
  ```
  Oczekiwane: `[OK] Wczytano dane dla roku 2026 z: coords/2026.csv` i ≈ 3.6e5. Dodatkowo `grep -n earrth lunar_stellarium.py`.
- [ ] **Step 3: Commit** `fix(lunar_stellarium): lowercase coords path, real night texture filename`

**Świadomie poza zakresem:**
- `newlunar.py` ma ten sam problem z nocną teksturą, martwe URL-e (DEM obchodzi cache) i macierz Cassiniego przesuniętą o ~0.4°. Plik jest nietykalny, więc zgłosimy to przy łączeniu w stronę.
- Integracja z backendem i frontem jest na później.

---

## Weryfikacja end-to-end

1. Wszystkie kroki „Weryfikacja uruchomieniem” z Task 1–4 przechodzą.
2. `git diff main --stat` pokazuje tylko `dte_line_of_sight.py`, `.gitignore`, `lunar_stellarium.py` i plan w `docs/`. `newlunar.py` jest bez zmian, a `git status` czysty.
3. Wywołania `--help` opisują flagi, a `python3 -c "import dte_line_of_sight"` niczego nie wypisuje.

## Wykonanie

Rekomenduję **Native**. Są 4 krótkie, sekwencyjne taski w jednym pliku, zależne od interfejsów poprzedników, a weryfikacja polega na uruchomieniu kodu. Na koniec jeden świeży reviewer sprawdzi całą gałąź: znaki w macierzach IAU, konwersję LDEM → układ `newlunar` (roll, kierunek wierszy) i zgodność formatu CSV z klawiszem C.
