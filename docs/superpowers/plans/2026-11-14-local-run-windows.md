# Uruchamianie /sim.html bez Dockera (Windows) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Druga osoba (Windows, bez Dockera) uruchamia `/sim.html` (Powierzchnia + Orbita) jednym poleceniem `py -3.12 run_local.py` i dostaje te same wyniki co kontener.

**Architecture:** Jeden root-skrypt `run_local.py` (standardowa biblioteka, bez zależności) odtwarza warunki z `Dockerfile`: wymusza Pythona 3.12, tworzy czysty `.venv` z `backend/requirements.txt` (bez pygame → ta sama atrapa z `app/core/legacy.py` co w Dockerze), sprawdza dane, startuje `uvicorn app.main:app` z `backend/` bez `--reload`. Ścieżki działają bez zmiennych `MODI_*`, bo `backend/app/settings.py` domyślnie liczy je względem roota repo. Do tego sekcja „Bez Dockera (Windows)” w `docs/ARCHITECTURE.md`.

**Tech Stack:** Python 3.12 (stdlib: `venv`, `subprocess`, `hashlib`, `argparse`), istniejące `backend/requirements.txt`, uvicorn 0.34.

**Spec:** prośba użytkownika w tej sesji: „2 osoba chce uruchomić ten projekt, ale nie ma Dockera… aby symulacje działały poprawnie i miały ten poziom zgodności”. Odpowiedzi: tylko strona `/sim.html` (nie skrypty pygame), system **Windows**, „chcemy to po prostu uruchomić teraz”, więc bez wzorców JSON i bez narzędzi do porównań w repo.

## Context

Dziś jedyna instrukcja bez Dockera to jedna linijka w `docs/ARCHITECTURE.md` (`cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`). Nie mówi ona o wersji Pythona. Na Windowsie domyślny `python` to zwykle 3.13/3.14 albo atrapa z Microsoft Store. Na 3.14 numba 0.61.2 i numpy 2.2.1 nie mają kół i `pip` się wywali. Docker używa `python:3.12-slim`.

Zgodność z Dockerem zapewniają rzeczy już obecne w repo, trzeba je tylko odtworzyć:

- **Stos numeryczny** jest przypięty w `backend/requirements.txt`: numpy 2.2.1, numba 0.61.2 (wymusza llvmlite 0.44.0), pandas 2.2.3, pydantic 2.10.4. Sprawdziłem `pip freeze` obrazu `lunarsims:prod`: różnice są tylko w pakietach serwera HTTP (np. websockets), więc plik lock jest zbędny.
- **Bez pygame:** świeży venv go nie ma, więc działa ta sama ścieżka z atrapą co w kontenerze.
- **Dane:** `Textures/` (mapy v3) i `coords/` są w git i przychodzą z klonem (~460 MB).
- **Kod:** `numba` używa zwykłego `@njit` (bez `fastmath`/`parallel`), więc wyniki nie zależą od liczby wątków. Backend czyta pliki jako bajty/UTF-8, więc polska strona kodowa Windowsa niczego nie psuje.

**Blokada:** `feat/sim-page` (z `/sim.html`) istnieje tylko lokalnie, 8 commitów przed `main` i nie ma jej na `origin`. Druga osoba nie ma czego sklonować, dopóki gałąź nie zostanie wypchnięta (Task 2).

## Global Constraints

- Python **dokładnie 3.12** (jak `FROM python:3.12-slim`). Każda inna wersja oznacza czytelny błąd z poleceniem instalacji, a nie próbę instalacji.
- Zależności tylko z `backend/requirements.txt`, bez dodawania pygame i bez nowego pliku lock.
- Venv w `<repo>/.venv` (już w `.gitignore`). Nie ruszamy `venv/` (lokalny 3.10 z pygame).
- Serwer na `127.0.0.1` (bez monitu zapory Windows), domyślnie port `8000`, bez `--reload`, cwd `backend/`.
- Env jak w `Dockerfile`: `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`, dodatkowo `PYTHONUTF8=1` (polskie komunikaty w konsoli Windows).
- Nie edytujemy `newlunar.py`, `neworb.py` ani fasad (fizyka 1:1).
- Brak testów automatycznych w modi2026: weryfikacja tylko uruchomieniem (curl/logi/przeglądarka).
- Komunikaty i dokumentacja po polsku. Commit z trailerem `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nie commitujemy cudzej zmiany w `backend/app/features/lunar_surface/facade.py` (dodajemy tylko własne ścieżki).

## Review Focus

1. **Zły Python** (`python` = 3.13/3.14, atrapa ze Store, lokalny 3.10). Oczekiwane: komunikat z `winget install -e --id Python.Python.3.12` i `py -3.12 run_local.py`, kod wyjścia 1, `.venv` nie powstaje (Task 1, krok 5a).
2. **Stary `.venv` z innego Pythona** (np. ktoś wcześniej zrobił `python -m venv .venv` na 3.13). Oczekiwane: komunikat „usuń .venv”, kod 1, bez instalacji na złym interpreterze (Task 1, krok 5b).
3. **Brak danych** (niepełny klon). Oczekiwane: lista brakujących plików i kod 1 przy starcie zamiast 503 z `lunar_surface/terrain` w przeglądarce (Task 1, krok 5c).
4. **Port 8000 zajęty** (np. Docker użytkownika). Oczekiwane: `--port 8001` działa, a dokumentacja o tym mówi (Task 1, krok 5d).
5. **`curl` w PowerShellu to alias `Invoke-WebRequest`.** Oczekiwane: dokumentacja używa `curl.exe` (Task 1, krok 2).

---

### Task 0: Zapis planu w repo

- [ ] Skopiuj ten plan do `docs/superpowers/plans/2026-11-14-local-run-windows.md` (konwencja repo). Commit razem z Task 1.

### Task 1: `run_local.py` + dokumentacja

**Files:**
- Create: `run_local.py` (root repo, obok `server.py`)
- Modify: `docs/ARCHITECTURE.md`, sekcja „## Uruchamianie”: linijkę „Bez Dockera: …” zastąp odsyłaczem do nowej podsekcji „### Bez Dockera (Windows i inne systemy)”

**Interfaces:**
- Produces: CLI `python run_local.py [--port N]` (domyślnie `8000`); kody wyjścia: `0` (Ctrl+C / normalne zakończenie), `1` (zła wersja Pythona, stary venv, brak danych, błąd `pip`), w pozostałych przypadkach kod uvicorna.
- Stałe w `run_local.py`: `REPO = Path(__file__).resolve().parent`, `VENV = REPO / ".venv"`, `REQUIREMENTS = REPO / "backend" / "requirements.txt"`, `PY_VERSION = (3, 12)`, `REQUIRED_DATA = ("Textures/moon_dem_nasa_16ppd_v3.npy", "Textures/moon_color_nasa_8k_v3.npy", "coords/2026.csv")` (pierwsze dwa to `DEM_FILE`/`COLOR_FILE` z `backend/app/features/lunar_surface/facade.py:33-34`).

- [ ] **Step 1: Napisz `run_local.py`** z funkcjami:
  - `check_python() -> None`: `sys.version_info[:2] != PY_VERSION` → komunikat (aktualna wersja, `winget install -e --id Python.Python.3.12` albo python.org, potem `py -3.12 run_local.py`) i `sys.exit(1)`.
  - `check_data() -> None`: brakujące pliki z `REQUIRED_DATA` → lista + wskazówka „sklonuj repo ponownie (git clone), nie pobieraj pojedynczych plików” i `sys.exit(1)`.
  - `venv_python() -> Path`: `VENV/"Scripts"/"python.exe"` gdy `os.name == "nt"`, inaczej `VENV/"bin"/"python"`.
  - `ensure_venv() -> Path`: gdy brak `.venv`, uruchom `[sys.executable, "-m", "venv", VENV]`. Gdy jest, a linia `version` w `VENV/"pyvenv.cfg"` nie zaczyna się od `3.12`, wypisz komunikat „usuń folder .venv i uruchom ponownie” i `sys.exit(1)`. Zależności instaluj (`[vpy, "-m", "pip", "install", "--disable-pip-version-check", "-r", REQUIREMENTS]`) tylko gdy sha256 `REQUIREMENTS` różni się od zawartości `VENV/"requirements.sha256"`. Znacznik zapisz dopiero po udanym `pip`. Niezerowy kod `pip` oznacza `sys.exit(1)`.
  - `main(argv=None) -> int`: argparse `--port` (int, 8000) → `check_python()` → `check_data()` → `ensure_venv()` → wypisz `Symulacja: http://127.0.0.1:<port>/sim.html` → `subprocess.call([vpy, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=REPO/"backend", env=os.environ | {PYTHONUTF8, PYTHONUNBUFFERED, PYTHONDONTWRITEBYTECODE = "1"})`. `KeyboardInterrupt` → `0`. Wybrałem `subprocess.call`, a nie `os.execv`, bo na Windowsie `execv` odłącza proces od konsoli.
  - Docstring modułu: po co skrypt jest i dlaczego jest zgodny z Dockerem (3.12, przypięcia, brak pygame = atrapa z `legacy.py`, ten sam `app.main:app`).

- [ ] **Step 2: Dopisz podsekcję w `docs/ARCHITECTURE.md`** (pod blokiem `docker compose` w „## Uruchamianie”):
  - **Wymagania:** Python 3.12 (`winget install -e --id Python.Python.3.12`), Git (`winget install -e --id Git.Git`), ~1 GB na dysku (klon ~460 MB + venv), RAM ≥ 8 GB (teren na biegunie chwilowo do ~4.3 GB), internet (pip przy pierwszym starcie, Three.js z CDN jsdelivr). Dostęp do repo `github.com/DoubleDuck77/MODI2026`.
  - **Kroki (PowerShell):** `git clone https://github.com/DoubleDuck77/MODI2026.git` → `cd MODI2026` → `git checkout feat/sim-page` (do czasu merge'a do `main`) → `py -3.12 run_local.py` → otwórz `http://127.0.0.1:8000/sim.html`. Pierwsze uruchomienie instaluje pakiety (kilka minut), kolejne startuje od razu.
  - **Dlaczego wyniki są takie jak w Dockerze:** 4 punkty z sekcji Context.
  - **Sprawdzenie:** `curl.exe -s http://127.0.0.1:8000/health` → `{"status":"ok","features":9}` oraz dwa zapytania z istniejącego bloku `/sim.html` (`lunar_surface/sky`, `lunar_orbit/initial`) w wersji z `curl.exe`.
  - **Problemy:** port zajęty → `py -3.12 run_local.py --port 8001`; „usuń .venv” → `Remove-Item -Recurse -Force .venv`; pierwsze zapytanie Orbity trwa kilka sekund (kompilacja numby), potem jest szybko; `python` otwiera Microsoft Store → używaj `py -3.12`.

- [ ] **Step 3: Commit** na `feat/sim-page` (druga osoba i tak musi pobrać tę gałąź). Tylko własne ścieżki:
  ```bash
  git add run_local.py docs/ARCHITECTURE.md docs/superpowers/plans/2026-11-14-local-run-windows.md
  git commit -m "feat: run_local.py — uruchamianie /sim.html bez Dockera (Python 3.12, Windows)"
  ```
  Poprawki z kroków 4–7 idą kolejnym commitem.

- [ ] **Step 4: Czysty klon i start na 3.12 (symulacja drugiej osoby).** Lokalnie jest tylko Python 3.10, więc 3.12 dajemy kontenerem z klonem w scratchpadzie:
  ```bash
  S=/tmp/claude-1000/-home-ihnat-code-htdocs-main-projects-modi2026/eed7a30c-bea0-412e-af7d-8b68d24956a1/scratchpad
  git clone -q --branch feat/sim-page /home/ihnat/code/htdocs/main_projects/modi2026 $S/clone
  docker run --rm --network host --user $(id -u):$(id -g) -e HOME=/tmp -v $S/clone:/repo -w /repo \
    python:3.12-slim python run_local.py --port 8001        # w tle
  curl -s 127.0.0.1:8001/health                             # {"status":"ok","features":9}
  ```
  Oczekiwane w logu: tworzenie `.venv`, `pip install`, `Symulacja: http://127.0.0.1:8001/sim.html`, `Uvicorn running on http://127.0.0.1:8001`. Drugi start bez `pip install`.

- [ ] **Step 5: Ścieżki błędów** (na klonie z kroku 4):
  - a) `python3 run_local.py` na hoście (3.10) → komunikat z `winget`/`py -3.12`, `echo $?` = 1, a `.venv` nie powstaje (sprawdź na świeżym klonie).
  - b) Linia `version` w `.venv/pyvenv.cfg` podmieniona na `3.13.0`, start kontenerem 3.12 jak w kroku 4 → „usuń .venv”, kod 1, brak `pip install`. Przywróć wartość.
  - c) `mv Textures/moon_color_nasa_8k_v3.npy{,.bak}` → lista z tym plikiem, kod 1. Przywróć.
  - d) Start na `--port 8001`, gdy `8000` zajmuje Docker → działa (pokrywa krok 6).

- [ ] **Step 6: Zgodność z Dockerem (jednorazowo, bez plików w repo).** Docker dev na `8000` (`docker compose up -d`) i lokalny na `8001` z tego samego commita:
  ```bash
  T=2026-11-20T12:00:00Z
  for q in "lunar_surface/sky?t=$T&lat_deg=-43.31&lon_deg=-11.36" \
           "lunar_surface/terrain?lat_deg=-89.5&lon_deg=0" \
           "lunar_orbit/initial?t=$T&preset=LRO" \
           "lunar_orbit/propagate?t=$T&x_km=1787.4&y_km=0&z_km=0&vx_kms=0&vy_kms=0&vz_kms=1.656&duration_s=600&sample_dt_s=60"; do
    cmp <(curl -s "localhost:8000/api/v1/$q") <(curl -s "localhost:8001/api/v1/$q") && echo "OK $q"
  done
  ```
  Oczekiwane: 4× `OK` (i żadna odpowiedź nie jest 422/503). Różnica w ostatnich cyfrach to wina CPU, nie konfiguracji. Zgłoś ją użytkownikowi, nie „naprawiaj”.

- [ ] **Step 7: Przeglądarka** (Playwright) na `http://127.0.0.1:8001/sim.html`: tryb Powierzchnia renderuje teren/niebo, tryb Orbita odtwarza tor, w konsoli brak błędów.

- [ ] **Step 8: Sprzątanie.** Zatrzymaj kontener, `rm -rf $S/clone`, `docker compose down`, jeśli Docker był włączony tylko na potrzeby testu. Ewentualne poprawki: commit.

### Task 2: Udostępnienie drugiej osobie (wymaga zgody użytkownika)

- [ ] **Step 1:** Zapytaj użytkownika, co zrobić z niezacommitowaną zmianą w `backend/app/features/lunar_surface/facade.py` (nie jest z tego planu) przed wypchnięciem.
- [ ] **Step 2:** Po zgodzie: `git push -u origin feat/sim-page`. Akcja zewnętrzna, więc bez zgody nie wypychamy. Druga osoba potrzebuje dostępu do repo `DoubleDuck77/MODI2026`.
- [ ] **Step 3:** Przekaż użytkownikowi gotowy tekst dla drugiej osoby: 4 polecenia z podsekcji „Bez Dockera” i link `http://127.0.0.1:8000/sim.html`.

## Weryfikacja końcowa

Odbiór robi druga osoba na Windowsie: `py -3.12 run_local.py` → oba tryby `/sim.html` działają, a `curl.exe -s http://127.0.0.1:8000/health` zwraca `features: 9`. Zgodność wyników sprawdzają lokalnie kroki 4 i 6 (3.12 z czystego klonu, wynik identyczny bajt w bajt z kontenerem).

## Wykonanie

Polecam tryb **Native**: to jeden mały plik i jedna sekcja dokumentacji, zadania nie mają między sobą interfejsów, a najdroższy możliwy błąd (zły Python / stary venv) wychodzi od razu w krokach 5a–5b.
