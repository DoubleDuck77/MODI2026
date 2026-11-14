# Szkielet architektury modułowej (FastAPI + HTML/JS + Docker) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Decyzja użytkownika: bez testów automatycznych i bez TDD** — każdy task kończy się ręcznym sprawdzeniem „czy działa” (curl / logi / przeglądarka).

**Goal:** Szkielet „contract-first”, w którym każda funkcjonalność (Lagrange, geografia Księżyca, cienie, horyzont, line-of-sight, korelacja położeń, wygląd Ziemi) jest osobnym modułem z kontraktem Pydantic i fasadą zwracającą przykładowy JSON z osobnego pliku, automatycznie wpiętym do FastAPI i do frontendu — bez implementacji obliczeń i renderingu.

**Architecture:** Pionowe moduły (vertical slices): backend `backend/app/features/<id>/`, przykład kontraktu `contracts/examples/<id>.<endpoint>.json`, warstwa frontu `frontend/js/features/<id>/layer.js`. Backend sam odkrywa moduły (pkgutil), generuje trasy z deskryptorów `Endpoint`, przy starcie waliduje każdy przykład JSON względem modelu, publikuje manifest `/api/v1/features`, z którego frontend dynamicznie importuje warstwy; dane zależne od czasu idą jednym zapytaniem `/api/v1/frame`. Dodanie funkcjonalności = dodanie folderów, zero edycji plików współdzielonych.

**Tech Stack:** Python 3.12 w kontenerze (składnia zgodna z 3.10), FastAPI 0.115.6, Pydantic 2.10.4, Uvicorn 0.34.0; vanilla ES modules + Three.js 0.170.0 (importmap z jsDelivr); Docker + docker compose.

**Spec:** prośba użytkownika z 2026-11-14 (cytat w sekcji Context). Przy wykonaniu skopiuj ten plik do `docs/superpowers/plans/2026-11-14-modular-architecture-skeleton.md` (Task 1).

---

## Context

Zespół hackathonowy (dużo osób równolegle) ma dziś w repo luźne skrypty: `lunar_stellarium.py` (pygame: widok z powierzchni Księżyca, Ziemia z teksturami dzień/noc/chmury), `solar system simulation.py` (N-body), `emphemeredis_downloader.py` (JPL Horizons → CSV), `time_zone_converter.py`, dane `coords/2000..2100.csv` (godzinowe wektory Słońca i Księżyca, geocentryczne, ekliptyka J2000) i tekstury 8K w `Textures/`.

Prośba: „rozdzielić architekturę … chcemy dodawać punkty Lagrange'a, geografię Księżyca, horyzont, skorelowanie położenia Księżyca i Ziemi … bardzo wydajną architekturę, aby każdy mógł na tym pracować … kontrakty oraz klasy bazowe … FastAPI + strona w HTML, CSS, JS … przykładowe struktury z klasami fasadami, gdzie one zwracają JSON, a te JSON-y trzymamy w osobnym pliku … wizualizacja Lagrange'a Ziemia–Księżyc, geografia Księżyca, góry, kratery, cienie, chmury kręcą się z inną prędkością niż planeta, w nocnej fazie Ziemi światła miast się przełączają, line-of-sight z Ziemią … nie pisz implementacji, tylko JSON-y, klasy bazowe i wszystko wpięte do FastAPI + HTML/JS/CSS z komunikacją, na Dockerze”. Doprecyzowanie: „nie ma testów, nie piszemy TDD, tylko testowanie czy działa”.

Efekt: `docker compose up` podnosi backend, strona pokazuje scenę Three.js (pustą, z osiami), panel warstw i inspektor JSON-ów płynących z każdego endpointu. Każdy zespół dostaje własny folder i gotowy kontrakt; backend nie wystartuje, jeśli przykład JSON rozjedzie się z modelem.

Fakty o danych odkryte przy analizie (ważne dla zespołów):
- `coords/*.csv` są w **metrach** (|moon| ≈ 3.61e8), mimo że downloader ma `OUT_UNITS='KM-S'`. Kontrakty używają km; przyszły provider musi dzielić przez 1000.
- Zakres danych: `2000-01-01 00:00` … `2100-01-01 00:00` (`2100.csv` ma jeden wiersz).
- Tekstura nocy nazywa się `Textures/earrth_night8K.jpg` (literówka w pliku; `lunar_stellarium.py` szuka `earth_night8K.jpg`). Kontrakty wskazują rzeczywistą nazwę; plików nie zmieniamy.
- Tekstury 8K mają 8192×4096, `moon_texture.jpg` 2048×1024.

## Global Constraints

- Bez testów automatycznych (pytest, `node --test`) i bez TDD; weryfikacja = uruchomienie i ręczne sprawdzenie.
- Nie modyfikować istniejących plików: `*.py` w root, `coords/`, `Textures/`.
- Składnia Python zgodna z 3.10: `timezone.utc` zamiast `datetime.UTC`, `class X(str, Enum)` zamiast `StrEnum`, bez PEP 695.
- `backend/app/core/routing.py` NIE może mieć `from __future__ import annotations` (FastAPI czyta adnotacje dynamicznie budowanych funkcji).
- Identyfikatory w kodzie po angielsku; docstringi, komentarze i `docs/ARCHITECTURE.md` po polsku.
- Jednostki w nazwach pól: `_km`, `_m`, `_deg`, `_deg_per_hour`; czas zawsze UTC, serializowany jako `2026-01-01T00:00:00Z`.
- Prefiks API: `/api/v1`. Ścieżka endpointu zawsze `/api/v1/{feature_id}/{endpoint_name}`, klucz `"{feature_id}.{endpoint_name}"`, plik przykładu `contracts/examples/{feature_id}.{endpoint_name}.json`, moduł frontu `/js/features/{feature_id}/layer.js`. Nic z tego nie jest konfigurowalne per zespół.
- `feature_id` i `endpoint_name`: regex `^[a-z][a-z0-9_]*$`.
- `CONTRACT_VERSION = "0.1.0"`; zakres czasu `DATA_START = 2000-01-01T00:00:00Z`, `DATA_END = 2100-01-01T00:00:00Z` (włącznie); `MAX_SERIES_POINTS = 2000`.
- Modele odpowiedzi dziedziczą `Contract` (`extra="forbid"`); modele zapytań dziedziczą zwykły `BaseModel` (nadmiarowe query params ignorowane).
- Każdy handler fasady zwraca wyłącznie `self.from_example(...)` (stub) + docstring „Prawdziwa implementacja: …”. Przykłady mają `meta.source = "example"`.
- Fasady są bezstanowe, jedna instancja na feature (tworzona przy starcie), metody synchroniczne (FastAPI wykonuje je w threadpoolu).
- Frontend: bez bundlera i bez zależności npm; Three.js `0.170.0` przez importmap: `"three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js"`, `"three/addons/": "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"`.
- Konwencje osi sceny (jedno miejsce prawdy: `frontend/js/core/units.js`): `KM_PER_SCENE_UNIT = 1000`; ekliptyka (x, y, z) → Three.js (x, z, −y); w widoku powierzchni N = −Z, E = +X, zenit = +Y.
- Cache-Control: endpointy `static` → `public, max-age=300`; `time_dependent` i `/frame` → `no-store`.
- Gałąź robocza: `feat/architecture-skeleton` (repo jest na `main`).

## Review Focus (sprawdzane ręcznie)

1. Czas spoza danych / z offsetem: `t=2101-01-01T00:00:00Z` → 422; `t=2026-01-01T01:00:00+01:00` → traktowane jak `2026-01-01T00:00:00Z`. Sprawdzenie: Task 3, krok Verify.
2. Przykład JSON rozjeżdża się z modelem → backend nie startuje, log wskazuje plik. Sprawdzenie: Task 3 (tymczasowo zepsuty przykład w Task 4).
3. Jedna padająca fasada nie zabija `/frame` → pozostałe payloady + mapa `errors`. Sprawdzenie: Task 4, krok Verify.
4. URL zasobu w kontrakcie wskazuje nieistniejący plik (np. `earth_night8K.jpg` zamiast `earrth_night8K.jpg`) → każdy `AssetRef.url` musi zwracać 200. Sprawdzenie: Task 12, krok 4.
5. Odpowiedzi `/frame` w złej kolejności przy odtwarzaniu/przewijaniu → starszy payload nie nadpisuje nowszego (AbortController + numer sekwencji) i maks. ~4 zapytania/s. Sprawdzenie: Task 12, krok 5 (zakładka sieci).

---

## Struktura plików

```
Dockerfile, docker-compose.yml, .dockerignore         # Task 1
docs/ARCHITECTURE.md                                  # Task 12 (przewodnik dla zespołów)
backend/
  requirements.txt                                    # Task 1
  app/main.py                                         # Task 3: create_app(), app
  app/settings.py                                     # Task 2
  app/core/contracts.py                               # Task 2: wspólne modele, zapytania, manifest/frame
  app/core/{feature,facade,context,providers,registry}.py   # Task 2: klasy bazowe i rejestr
  app/core/routing.py                                 # Task 3: trasy feature, /frame, /features
  app/features/<id>/{__init__.py,contract.py,facade.py}     # Task 4–10 (jeden folder na zespół)
contracts/examples/<id>.<endpoint>.json               # Task 4–10 (źródło prawdy dla frontu)
frontend/
  index.html, css/main.css, js/main.js                # Task 11
  js/core/{units,clock,frame-scheduler,api-client,observer,scene,base-layer,layer-loader}.js  # Task 11
  js/ui/{controls,layer-panel,inspector}.js           # Task 11
  js/features/<id>/layer.js                           # Task 12 (stuby warstw)
```

Moduły (właściciel = jeden zespół):

| feature_id | view | endpointy (klucz → params) |
|---|---|---|
| `ephemeris` | space | `state` → TimeQuery, frame; `series` → RangeQuery |
| `lagrange` | space | `points` → TimeQuery, frame |
| `moon_geography` | space | `features` → static; `terrain` → static |
| `moon_illumination` | space | `state` → TimeQuery, frame |
| `horizon` | surface | `view` → ObserverQuery, frame |
| `line_of_sight` | surface | `point` → ObserverQuery, frame; `windows` → ObserverRangeQuery |
| `earth_appearance` | space | `state` → TimeQuery, frame |

Zmienna pomocnicza do kroków Verify: `T=2026-01-01T00:00:00Z`, `API=http://localhost:8000/api/v1`. Backend działa przez `docker compose up -d` (wolumeny + `--reload`, więc zmiany kodu i JSON-ów są widoczne bez przebudowy; logi: `docker compose logs -f api`).

---

### Task 1: Gałąź, zależności, Docker

**Files:**
- Create: `docs/superpowers/plans/2026-11-14-modular-architecture-skeleton.md` (kopia tego planu)
- Create: `backend/requirements.txt`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/features/__init__.py`, `backend/app/main.py` (tymczasowo: `app = FastAPI()` + `GET /health` → `{"status": "ok"}`; Task 3 zastępuje)
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `contracts/examples/.gitkeep`, `frontend/.gitkeep`

**Interfaces:**
- Produces: obraz `api` z `/srv/backend` (workdir), `/srv/contracts`, `/srv/frontend`, `/data/textures`, `/data/coords`; env `MODI_CONTRACTS_DIR=/srv/contracts`, `MODI_FRONTEND_DIR=/srv/frontend`, `MODI_TEXTURES_DIR=/data/textures`, `MODI_COORDS_DIR=/data/coords`.

- [ ] **Step 1:** `git switch -c feat/architecture-skeleton`; skopiuj plan do `docs/superpowers/plans/`.
- [ ] **Step 2:** `requirements.txt`: `fastapi==0.115.6`, `uvicorn[standard]==0.34.0`, `pydantic==2.10.4`, `numpy==2.2.1`, `pandas==2.2.3` (numpy/pandas od razu, żeby zespoły nie konfliktowały na tym pliku).
- [ ] **Step 3:** `Dockerfile` (root): `python:3.12-slim`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, workdir `/srv/backend`, `pip install --no-cache-dir -r requirements.txt`, `COPY backend/ ./`, `COPY contracts/ /srv/contracts/`, `COPY frontend/ /srv/frontend/`, env jak w Interfaces, `EXPOSE 8000`, `HEALTHCHECK` przez `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"`, `CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]`.
- [ ] **Step 4:** `docker-compose.yml`: serwis `api`, `build: .`, `ports: ["8000:8000"]`, wolumeny `./backend:/srv/backend`, `./contracts:/srv/contracts`, `./frontend:/srv/frontend`, `./Textures:/data/textures:ro`, `./coords:/data/coords:ro`; `command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /srv/backend/app --reload-dir /srv/contracts --reload-include '*.json'`. `.dockerignore`: `.git`, `Textures`, `coords`, `**/__pycache__`, `*.npz`, `*.png`, `.venv`.
- [ ] **Step 5 (Verify):** `docker compose up -d --build && sleep 3 && curl -sf localhost:8000/health` → `{"status":"ok"}`; `docker compose ps` → `api` w stanie `healthy` (po ~30 s).
- [ ] **Step 6:** Commit: `git add Dockerfile docker-compose.yml .dockerignore backend contracts frontend docs && git commit -m "chore: scaffold backend package and docker setup"`

---

### Task 2: Kontrakty wspólne i klasy bazowe

**Files:**
- Create: `backend/app/core/contracts.py`, `backend/app/settings.py`, `backend/app/core/context.py`, `backend/app/core/providers.py`, `backend/app/core/facade.py`, `backend/app/core/feature.py`, `backend/app/core/registry.py`

**Interfaces:**
- Produces — `app.core.contracts`:
  - stałe `CONTRACT_VERSION`, `DATA_START`, `DATA_END`, `MAX_SERIES_POINTS`
  - `class Contract(BaseModel)` — `model_config = ConfigDict(extra="forbid")`
  - `Vec3(Contract)`: `x, y, z: float`
  - `GeoPoint(Contract)`: `lat_deg: float [-90, 90]`, `lon_deg: float [-180, 180]`; `SelenoPoint(GeoPoint)` (to samo na Księżycu)
  - `AltAz(Contract)`: `alt_deg [-90, 90]`, `az_deg [0, 360)` (od N zgodnie z ruchem wskazówek), `distance_km > 0`
  - `AssetRef(Contract)`: `url: str`, `width: int | None = None`, `height: int | None = None`, `format: str`
  - `ReferenceFrame(str, Enum)`: `ECLIPTIC_J2000_GEOCENTRIC`, `EARTH_MOON_ROTATING`, `MOON_BODY_FIXED`, `EARTH_BODY_FIXED`, `TOPOCENTRIC_HORIZON` (wartości = nazwy)
  - `TimeDependency(str, Enum)`: `STATIC="static"`, `TIME_DEPENDENT="time_dependent"`; `View(str, Enum)`: `SPACE="space"`, `SURFACE="surface"`
  - `ResponseMeta(Contract)`: `feature: str`, `endpoint: str`, `contract_version: str`, `source: Literal["example", "computed"]`, `frame: ReferenceFrame | None = None`, `units: dict[str, str] = {}`
  - `FeatureResponse(Contract)`: `meta: ResponseMeta` — baza każdej odpowiedzi feature
  - Zapytania (`BaseModel`): `TimeQuery`: `t: datetime`; `ObserverFields`: `lat_deg: float = 0.0 [-90,90]`, `lon_deg: float = 0.0 [-180,180]`; `ObserverQuery(TimeQuery, ObserverFields)`; `RangeQuery`: `start: datetime`, `end: datetime`, `step_hours: int = 1 [1, 24]`, property `point_count -> int` = `floor((end-start)/step)+1`; `ObserverRangeQuery(RangeQuery, ObserverFields)`; `FrameQuery(ObserverQuery)`: `keys: str | None = None` (lista po przecinku)
  - Walidacja czasu: jedna funkcja `_to_utc_in_range(v: datetime) -> datetime` (naive → `replace(tzinfo=utc)`, inaczej `astimezone(utc)`, potem `DATA_START <= v <= DATA_END`) jako `field_validator(mode="after")` dla `t`, `start`, `end`; `RangeQuery` ma `model_validator(mode="after")`: `end > start` i `point_count <= MAX_SERIES_POINTS`
  - `BodyVectors(Contract)`: `t: datetime`, `sun_km: Vec3`, `moon_km: Vec3` (dla interfejsu providera)
  - Manifest/klatka: `EndpointInfo(Contract)`: `key, name, path: str`, `time_dependency: TimeDependency`, `frame: bool`; `FeatureInfo(Contract)`: `id, title, description: str`, `view: View`, `frontend_module: str`, `endpoints: list[EndpointInfo]`; `FeatureManifest(Contract)`: `contract_version: str`, `features: list[FeatureInfo]`; `FrameResponse(Contract)`: `t: datetime`, `observer: SelenoPoint`, `payloads: dict[str, dict[str, Any]]`, `errors: dict[str, str]`
- Produces — reszta:
  - `Settings` (frozen dataclass, `app/settings.py`): `contracts_dir, frontend_dir, textures_dir, coords_dir: Path`; property `examples_dir = contracts_dir / "examples"`; `@classmethod from_env() -> Settings` (zmienne `MODI_*`, domyślnie względem roota repo = `Path(__file__).resolve().parents[2]`: `contracts`, `frontend`, `Textures`, `coords`), żeby `uvicorn` działał też bez Dockera.
  - `AppContext` (dataclass): `settings: Settings`, `ephemeris: EphemerisProvider | None = None`, `terrain: TerrainProvider | None = None`.
  - `providers.py` (ABC, bez implementacji): `EphemerisProvider.state_at(t: datetime) -> BodyVectors`, `EphemerisProvider.series(start: datetime, end: datetime, step: timedelta) -> list[BodyVectors]`; `TerrainProvider.elevation_m(p: SelenoPoint) -> float`, `TerrainProvider.horizon_profile(observer: SelenoPoint, az_step_deg: float) -> list[float]`. Docstring: CSV jest w metrach, provider zwraca km; fasady korzystają z providerów przez `ctx`, nigdy przez HTTP do innych modułów.
  - `BaseFacade`: `feature_id: ClassVar[str]`; `__init__(self, ctx: AppContext)` → `self.ctx`; `from_example(self, endpoint: str, model: type[R]) -> R` — czyta `{examples_dir}/{feature_id}.{endpoint}.json` przez cache'owany `_read_bytes(path) -> bytes` (`functools.lru_cache`) i zwraca `model.model_validate_json(...)`; brak pliku → `ExampleNotFoundError(FileNotFoundError)` z pełną ścieżką.
  - `Endpoint` (frozen dataclass, `feature.py`): `name: str`, `handler: str`, `response: type[FeatureResponse]`, `params: type[BaseModel] | None = None`, `time_dependency: TimeDependency = TimeDependency.TIME_DEPENDENT`, `frame: bool = False`, `summary: str = ""`.
  - `FeatureModule` (frozen dataclass): `id, title, description: str`, `view: View`, `facade: type[BaseFacade]`, `endpoints: tuple[Endpoint, ...]`; `key(ep) -> str`, `path(ep) -> str` (`/{id}/{name}`, bez prefiksu), property `frontend_module`.
  - `discover_features(package: str = "app.features") -> list[FeatureModule]` — iteruje podpakiety (pomija `_*`), wymaga atrybutu `FEATURE`, sortuje po `id`.
  - `FeatureRegistryError(Exception)`; `FeatureRegistry(features: list[FeatureModule], ctx: AppContext)` z metodami: `features()`, `facade(feature_id) -> BaseFacade`, `endpoint(key) -> tuple[FeatureModule, Endpoint]` (`KeyError` dla nieznanych), `frame_keys() -> list[str]` (posortowane), `call(key, params: BaseModel | None) -> FeatureResponse`.
  - Walidacja w `FeatureRegistry.__init__` (każdy błąd → `FeatureRegistryError` z id feature w treści): zduplikowane id; regex id i nazw endpointów; duplikat nazwy endpointu; `facade.feature_id != feature.id`; brak metody `handler` na fasadzie; brak pliku przykładu (komunikat z nazwą pliku); przykład nie przechodzi walidacji `endpoint.response` (komunikat z nazwą pliku i błędem Pydantic); `STATIC` z `params`; `frame=True` gdy nie `TIME_DEPENDENT`, `params is None` albo pola `params` nie są podzbiorem `ObserverQuery.model_fields`.

- [ ] **Step 1:** Utwórz pliki wg Interfaces.
- [ ] **Step 2 (Verify):** `docker compose exec api python -c "from app.core.contracts import TimeQuery; from app.core.registry import FeatureRegistry, discover_features; print(TimeQuery(t='2026-01-01T01:00:00+01:00').t, discover_features())"` → `2026-01-01 00:00:00+00:00 []`. `docker compose exec api python -c "from app.core.contracts import TimeQuery; TimeQuery(t='2101-01-01T00:00:00Z')"` → `ValidationError`.
- [ ] **Step 3:** Commit: `git commit -m "feat(core): shared contracts, base facade, feature descriptors, registry"`

---

### Task 3: Routing, manifest, `/frame`, fabryka aplikacji

**Files:**
- Create: `backend/app/core/routing.py`
- Modify: `backend/app/main.py` (zastąp wersję tymczasową z Task 1)

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `API_PREFIX = "/api/v1"` (w `app.main`)
  - `build_feature_router(registry) -> APIRouter`, `build_manifest_router(registry) -> APIRouter` (`GET /features` → `FeatureManifest`, `EndpointInfo.path` z prefiksem `/api/v1`), `build_frame_router(registry) -> APIRouter` (`GET /frame` → `FrameResponse`)
  - `create_app(settings: Settings | None = None, features: list[FeatureModule] | None = None) -> FastAPI` — domyślnie `Settings.from_env()` i `discover_features()`; `app.state.registry`; `GET /health` → `{"status": "ok", "features": <liczba>}`; `GZipMiddleware(minimum_size=1024)`; mount `/textures` → `StaticFiles(directory=textures_dir, check_dir=False)`; mount `/` → `StaticFiles(directory=frontend_dir, html=True, check_dir=False)` jako ostatni.
  - moduł-level `app = create_app()`

Algorytm budowy trasy (adnotacje muszą być prawdziwymi obiektami — patrz Global Constraints):

```python
def _make_route(registry, key, ep):
    cache = "public, max-age=300" if ep.time_dependency is TimeDependency.STATIC else "no-store"
    if ep.params is None:
        def route(response: Response):
            response.headers["Cache-Control"] = cache
            return registry.call(key, None)
    else:
        def route(response: Response, params: Annotated[ep.params, Query()]):
            response.headers["Cache-Control"] = cache
            return registry.call(key, params)
    return route
# router.add_api_route(feature.path(ep), _make_route(...), methods=["GET"],
#     response_model=ep.response, name=key, summary=ep.summary, tags=[feature.id])
```

`/frame`: `keys=None` → `registry.frame_keys()`; inaczej split po `,` + strip; nieznane lub nie-frame klucze → `HTTPException(422, detail={"invalid_keys": [...]})`; każdy klucz: `ep.params.model_validate(query.model_dump(include=set(ep.params.model_fields)))`, wynik `.model_dump(mode="json")` do `payloads`; wyjątek fasady → `errors[key] = f"{type(e).__name__}: {e}"` + `logger.exception`; nagłówek `no-store`.

- [ ] **Step 1:** Utwórz `routing.py`, przepisz `main.py`.
- [ ] **Step 2 (Verify):** `curl -sf localhost:8000/health` → `{"status":"ok","features":0}`; `curl -sf $API/features` → `{"contract_version":"0.1.0","features":[]}`; `curl -s "$API/frame?t=$T"` → `payloads: {}`, `errors: {}`; `curl -s -o /dev/null -w '%{http_code}' "$API/frame?t=2101-01-01T00:00:00Z"` → `422`; `http://localhost:8000/docs` otwiera się.
- [ ] **Step 3:** Commit: `git commit -m "feat(api): generated feature routes, manifest, batched frame endpoint"`

---

### Wzorzec modułu feature (Task 4–10)

Każdy z Task 4–10 tworzy ten sam zestaw:
- `backend/app/features/<id>/contract.py` — modele odpowiedzi; walidatory strukturalne jako `model_validator(mode="after")` (pilnują przykładów przy starcie i przyszłych obliczeń).
- `backend/app/features/<id>/facade.py` — `<Name>Facade(BaseFacade)`, `feature_id = "<id>"`; każda metoda `(self, q: <Query>) -> <Model>` lub `(self) -> <Model>`, docstring „Prawdziwa implementacja: …”, ciało `return self.from_example("<endpoint>", <Model>)`.
- `backend/app/features/<id>/__init__.py` — `FEATURE = FeatureModule(...)`.
- `contracts/examples/<id>.<endpoint>.json` — z `meta`: `feature`, `endpoint`, `contract_version: "0.1.0"`, `source: "example"`, `frame`, `units`.

Weryfikacja każdego modułu (krok Verify): `docker compose logs api | tail -20` bez `FeatureRegistryError`; `curl -sf localhost:8000/health` → liczba features wzrosła o 1; każdy endpoint modułu `curl -sf "$API/<id>/<endpoint>?t=$T" | python3 -m json.tool | head -30` → 200 i `"source": "example"`; dla endpointów frame `curl -s "$API/frame?t=$T" | python3 -c "import sys,json; b=json.load(sys.stdin); print(sorted(b['payloads']), b['errors'])"` → klucz modułu obecny, `errors` puste.

Liczby w przykładach policzono z `coords/2026.csv` (2026-01-01 00:00 UTC) albo z katalogów selenograficznych.

---

### Task 4: `ephemeris` (korelacja Ziemia–Księżyc–Słońce)

**Files:** `backend/app/features/ephemeris/{__init__,contract,facade}.py`, `contracts/examples/ephemeris.state.json`, `contracts/examples/ephemeris.series.json`

**Interfaces:**
- `MoonPhase(Contract)`: `phase_angle_deg [0,180]`, `illuminated_fraction [0,1]`, `waxing: bool`, `name: Literal["new","waxing_crescent","first_quarter","waxing_gibbous","full","waning_gibbous","last_quarter","waning_crescent"]`
- `EphemerisState(FeatureResponse)`: `t`, `sun_km: Vec3`, `moon_km: Vec3` (geocentryczne, `ECLIPTIC_J2000_GEOCENTRIC`), `earth_moon_distance_km > 0`, `earth_sun_distance_km > 0`, `elongation_deg [0,180]`, `moon_phase: MoonPhase`, `earth_illuminated_fraction_from_moon [0,1]`
- `EphemerisSeries(FeatureResponse)`: `start: datetime`, `step_hours: int ≥ 1`, `sun_km: list[tuple[float, float, float]]`, `moon_km: list[tuple[float, float, float]]` (kolumnowo, mały JSON); walidator: równe długości, ≥ 1
- `EphemerisFacade.state(q: TimeQuery) -> EphemerisState`, `.series(q: RangeQuery) -> EphemerisSeries` (docstringi: `ctx.ephemeris`, interpolacja liniowa między godzinami jak `get_topocentric_vectors` w `lunar_stellarium.py:63`)
- `FEATURE`: title „Efemerydy i korelacja Ziemia–Księżyc–Słońce”, view SPACE; `state` (TimeQuery, frame), `series` (RangeQuery)
- Example pins — `ephemeris.state.json`: `t 2026-01-01T00:00:00Z`; `sun_km (26072138.448, -144774673.821, 8892.862)`; `moon_km (144325.727, 329395.831, 31752.976)`; `earth_moon_distance_km 361026.0`; `earth_sun_distance_km 147103578.0`; `elongation_deg 145.8`; `moon_phase {34.121, 0.9139, waxing true, "waxing_gibbous"}`; `earth_illuminated_fraction_from_moon 0.0861`; `meta.units {"distance":"km","angle":"deg"}`. `ephemeris.series.json`: `start 2026-01-01T00:00:00Z`, `step_hours 1`, sun `(26072138.448, -144774673.821, 8892.862)`, `(26179371.451, -144755208.36, 8891.36)`, `(26286590.119, -144735665.134, 8889.81)`; moon `(144325.727, 329395.831, 31752.976)`, `(140702.161, 330892.761, 31771.31)`, `(137062.789, 332353.2, 31786.093)`.

- [ ] **Step 1:** Utwórz moduł wg wzorca i pinów.
- [ ] **Step 2 (Verify):** wg wzorca; `series`: `curl -sf "$API/ephemeris/series?start=$T&end=2026-01-01T02:00:00Z"` → 200. Sprawdzenie Review Focus #2: tymczasowo zmień w `ephemeris.state.json` `"elongation_deg"` na `"elongation"` → log `FeatureRegistryError` z `ephemeris.state.json`, `/health` nie odpowiada; cofnij → backend wraca.
- [ ] **Step 3:** Commit: `git commit -m "feat(ephemeris): contract, stub facade and examples"`

---

### Task 5: `lagrange`

**Files:** `backend/app/features/lagrange/{__init__,contract,facade}.py`, `contracts/examples/lagrange.points.json`

**Interfaces:**
- `LagrangePoint(Contract)`: `id: Literal["L1","L2","L3","L4","L5"]`, `position_km: Vec3` (geocentryczne, ekliptyka), `position_rotating: Vec3` (bezwymiarowe, środek w barycentrum, jednostka = odległość Z–K), `distance_from_earth_km`, `distance_from_moon_km`, `stable: bool`
- `RotatingFrame(Contract)`: `origin: Literal["earth_moon_barycenter"]`, `x_axis, y_axis, z_axis: Vec3` (wersory w ekliptyce)
- `LagrangePoints(FeatureResponse)`: `t`, `mass_ratio: float (0, 0.5)`, `earth_moon_distance_km`, `rotating_frame`, `points: list[LagrangePoint]` — walidator: id dokładnie `L1..L5` w tej kolejności
- `LagrangeFacade.points(q: TimeQuery) -> LagrangePoints` (docstring: CR3BP, oś x w stronę Księżyca, z = normalna orbity z r×v). FEATURE: title „Punkty Lagrange'a Ziemia–Księżyc”, view SPACE, `points` frame.
- Example pins: `mass_ratio 0.012150585`, `earth_moon_distance_km 361026.0`, osie `x (0.399765, 0.912388, 0.087952)`, `y (-0.916148, 0.400787, 0.006499)`, `z (-0.029321, -0.083175, 0.996104)`; punkty (position_km / rotating / dE / dM / stable):
  L1 `(122542.0, 279678.7, 26960.4)` / `(0.836915,0,0)` / 306534.8 / 54491.2 / false;
  L2 `(168548.3, 384679.2, 37082.2)` / `(1.155682,0,0)` / 421617.9 / 60591.9 / false;
  L3 `(-143302.8, -327061.2, -31527.9)` / `(-1.005063,0,0)` / 358467.2 / 719493.2 / false;
  L4 `(-214278.0, 290006.9, 17908.3)` / `(0.487849, 0.866025, 0)` / 361026.0 / 361026.0 / true;
  L5 `(358603.7, 39388.9, 13844.6)` / `(0.487849, -0.866025, 0)` / 361026.0 / 361026.0 / true.

- [ ] **Step 1:** Utwórz moduł wg wzorca i pinów.
- [ ] **Step 2 (Verify):** wg wzorca.
- [ ] **Step 3:** Commit: `git commit -m "feat(lagrange): contract, stub facade and example"`

---

### Task 6: `moon_geography` (kratery, góry, morza, teren)

**Files:** `backend/app/features/moon_geography/{__init__,contract,facade}.py`, `contracts/examples/moon_geography.features.json`, `contracts/examples/moon_geography.terrain.json`

**Interfaces:**
- `MoonFeature(Contract)`: `id: str` (regex `^[a-z0-9_]+$`), `name: str`, `kind: Literal["crater","mountain","mare"]`, `center: SelenoPoint`, `diameter_km > 0`, `depth_km: float | None = None`, `height_m: float | None = None` — walidator: crater ⇒ `depth_km`, mountain ⇒ `height_m`
- `MoonFeatureCatalog(FeatureResponse)`: `features: list[MoonFeature]` — walidator unikalnych id
- `MoonTerrain(FeatureResponse)`: `radius_km`, `projection: Literal["equirectangular"]`, `lon_origin_deg: float = -180.0` (u=0 tekstury), `color_map: AssetRef`, `color_map_preview: AssetRef`, `height_map: AssetRef | None`, `normal_map: AssetRef | None`, `height_range_m: tuple[float, float]` (piksel 0..255 → min..max)
- `MoonGeographyFacade.features() -> MoonFeatureCatalog`, `.terrain() -> MoonTerrain`. FEATURE: title „Geografia Księżyca: kratery, góry, morza”, view SPACE, oba endpointy STATIC.
- Example pins — features (id, name, kind, lat, lon, diameter_km, depth_km/height_m): `tycho` Tycho crater −43.31 −11.36 85 d4.8; `copernicus` Copernicus crater 9.62 −20.08 93 d3.8; `clavius` Clavius crater −58.62 −14.73 225 d3.5; `shackleton` Shackleton crater −89.67 129.78 21 d4.2; `mons_huygens` Mons Huygens mountain 19.92 −2.86 40 h5500; `mons_hadley` Mons Hadley mountain 26.69 4.12 25 h4500; `mare_imbrium` Mare Imbrium mare 32.8 −15.6 1145. Terrain: `radius_km 1737.4`, `color_map {/textures/moon_texture8K.jpg, 8192, 4096, "jpg"}`, `color_map_preview {/textures/moon_texture.jpg, 2048, 1024, "jpg"}`, `height_map null`, `normal_map null`, `height_range_m [-9100, 10786]`.

- [ ] **Step 1:** Utwórz moduł wg wzorca i pinów.
- [ ] **Step 2 (Verify):** wg wzorca (bez `?t=`); `curl -sI $API/moon_geography/features | grep -i cache-control` → `public, max-age=300`; `curl -sI localhost:8000/textures/moon_texture.jpg` → `200`.
- [ ] **Step 3:** Commit: `git commit -m "feat(moon_geography): feature catalog and terrain contracts"`

---

### Task 7: `moon_illumination` (cienie)

**Files:** `backend/app/features/moon_illumination/{__init__,contract,facade}.py`, `contracts/examples/moon_illumination.state.json`

**Interfaces:**
- Consumes: id z `moon_geography.features.json` (`feature_id` w cieniach musi tam istnieć).
- `FeatureShadow(Contract)`: `feature_id: str`, `sun_elevation_deg [-90,90]`, `shadow_length_km: float | None`, `in_shadow: bool` — walidator: `in_shadow == (sun_elevation_deg <= 0)` oraz `shadow_length_km is None` ⇔ `in_shadow`
- `MoonIllumination(FeatureResponse)`: `t`, `sun_dir_body: Vec3`, `earth_dir_body: Vec3` (wersory, `MOON_BODY_FIXED`), `subsolar_point: SelenoPoint`, `sub_earth_point: SelenoPoint` (libracja), `terminator: list[SelenoPoint]` (min. 3), `shadows: list[FeatureShadow]`
- `MoonIlluminationFacade.state(q: TimeQuery) -> MoonIllumination` (docstring: macierz ciała jak `get_lunar_body_matrix`, `lunar_stellarium.py:56`; cień ≈ głębokość / tan(elewacja)). FEATURE: title „Oświetlenie i cienie Księżyca”, view SPACE, `state` frame.
- Example pins: `subsolar_point (1.2, 34.5)`, `sun_dir_body (0.823945, 0.566282, 0.020942)`; `sub_earth_point (-2.9, 1.8)`, `earth_dir_body (0.998227, 0.031371, -0.050593)`; terminator (lat, lon): `(0.0,124.5) (44.99,125.7) (88.8,-145.5) (44.99,-56.7) (0.0,-55.5) (-44.99,-54.3) (-88.8,34.5) (-44.99,123.3)`; shadows (feature_id / elev / length / in_shadow): `tycho 29.49 / 8.5 / false`, `copernicus 35.08 / 5.4 / false`, `clavius 18.79 / 10.3 / false`, `shackleton -1.23 / null / true`.

- [ ] **Step 1:** Utwórz moduł wg wzorca i pinów.
- [ ] **Step 2 (Verify):** wg wzorca.
- [ ] **Step 3:** Commit: `git commit -m "feat(moon_illumination): sun direction, terminator and shadow contracts"`

---

### Task 8: `horizon`

**Files:** `backend/app/features/horizon/{__init__,contract,facade}.py`, `contracts/examples/horizon.view.json`

**Interfaces:**
- `HorizonProfile(Contract)`: `az_step_deg (0, 90]`, `elevation_deg: list[float]` (indeks i ↔ azymut i·krok, N=0, E=90) — walidator: `abs(len * step − 360) < 1e-6`
- `LocalBasis(Contract)`: `north, east, up: Vec3` (`MOON_BODY_FIXED`)
- `HorizonView(FeatureResponse)`: `t`, `observer: SelenoPoint`, `observer_elevation_m: float`, `profile`, `earth: AltAz`, `sun: AltAz`, `local_basis`. Krok profilu wybiera backend (front czyta `az_step_deg` z payloadu).
- `HorizonFacade.view(q: ObserverQuery) -> HorizonView` (docstring: `ctx.terrain.horizon_profile`, alt/az jak `to_alt_az` w `lunar_stellarium.py:104`). FEATURE: title „Horyzont obserwatora na Księżycu”, view SURFACE, `view` frame.
- Example pins: observer `(0, 0)`, `observer_elevation_m 0.0`, profile step `30`, wartości `[0.8, 1.1, 0.6, 0.3, 0.9, 1.4, 2.1, 1.7, 0.9, 0.5, 0.4, 0.7]`; `earth (86.59, 148.2, 359290.0)`; `sun (55.48, 87.88, 147402800.0)`; basis `north (0,0,1)`, `east (0,1,0)`, `up (1,0,0)`; `meta.frame "TOPOCENTRIC_HORIZON"`.

- [ ] **Step 1:** Utwórz moduł wg wzorca i pinów.
- [ ] **Step 2 (Verify):** wg wzorca, dodatkowo `curl -s -o /dev/null -w '%{http_code}' "$API/horizon/view?t=$T&lat_deg=91"` → `422`.
- [ ] **Step 3:** Commit: `git commit -m "feat(horizon): observer horizon contract"`

---

### Task 9: `line_of_sight`

**Files:** `backend/app/features/line_of_sight/{__init__,contract,facade}.py`, `contracts/examples/line_of_sight.point.json`, `contracts/examples/line_of_sight.windows.json`

**Interfaces:**
- `LineOfSight(FeatureResponse)`: `t`, `observer: SelenoPoint`, `earth: AltAz`, `horizon_elevation_deg: float` (teren w azymucie Ziemi), `clearance_deg: float`, `visible_disk_fraction [0,1]`, `earth_visible: bool`, `blocked_by: str | None` (id z `moon_geography`) — walidatory: `abs(clearance_deg − (earth.alt_deg − horizon_elevation_deg)) < 1e-6`, `earth_visible == (visible_disk_fraction > 0)`
- `VisibilityWindow(Contract)`: `start, end: datetime`, `max_clearance_deg` — walidator `start < end`
- `VisibilityWindows(FeatureResponse)`: `observer`, `start`, `end`, `step_hours`, `windows: list[VisibilityWindow]`, `visible_fraction [0,1]` — walidator: okna posortowane, rozłączne, w `[start, end]`
- `LineOfSightFacade.point(q: ObserverQuery) -> LineOfSight`, `.windows(q: ObserverRangeQuery) -> VisibilityWindows` (docstring: korzysta z `ctx.terrain` i `ctx.ephemeris`). FEATURE: title „Line-of-sight do Ziemi”, view SURFACE; `point` frame, `windows` time_dependent.
- Example pins — point: observer `(0,0)`, `earth (86.59, 148.2, 359290.0)`, `horizon_elevation_deg 1.37`, `clearance_deg 85.22`, `visible_disk_fraction 1.0`, `earth_visible true`, `blocked_by null`. Windows: observer `(0, 90)`, `start 2026-01-01T00:00:00Z`, `end 2026-02-01T00:00:00Z`, `step_hours 1`, okna `2026-01-03T05:00:00Z → 2026-01-16T19:00:00Z max 6.8`, `2026-01-30T11:00:00Z → 2026-02-01T00:00:00Z max 2.1`, `visible_fraction 0.4879`.

- [ ] **Step 1:** Utwórz moduł wg wzorca i pinów.
- [ ] **Step 2 (Verify):** wg wzorca; `windows`: `curl -sf "$API/line_of_sight/windows?start=$T&end=2026-02-01T00:00:00Z&lat_deg=0&lon_deg=90"` → 200; `...&end=2026-06-01T00:00:00Z` (> 2000 punktów) → `422`. Sprawdzenie Review Focus #3: tymczasowo `raise RuntimeError("boom")` w `LineOfSightFacade.point` → `/frame?t=$T` zwraca 200, pozostałe payloady obecne, `errors["line_of_sight.point"]` zawiera `boom`; cofnij.
- [ ] **Step 3:** Commit: `git commit -m "feat(line_of_sight): point visibility and windows contracts"`

---

### Task 10: `earth_appearance` (rotacja, chmury, światła miast)

**Files:** `backend/app/features/earth_appearance/{__init__,contract,facade}.py`, `contracts/examples/earth_appearance.state.json`

**Interfaces:**
- `BodyRotation(Contract)`: `angle_deg [0,360)`, `rate_deg_per_hour > 0`
- `CloudLayer(Contract)`: `texture: AssetRef`, `angle_deg [0,360)`, `rate_deg_per_hour: float`, `altitude_km > 0`
- `CityLight(Contract)`: `name: str`, `location: GeoPoint`, `sun_elevation_deg [-90,90]`, `lights_on: bool`
- `CityLights(Contract)`: `on_below_sun_elevation_deg: float`, `fade_deg > 0`, `cities: list[CityLight]` — walidator: `lights_on == (sun_elevation_deg <= on_below_sun_elevation_deg)` dla każdego miasta
- `EarthAppearance(FeatureResponse)`: `t`, `axial_tilt_deg`, `rotation: BodyRotation`, `clouds: CloudLayer`, `subsolar_point: GeoPoint`, `day_texture: AssetRef`, `night_texture: AssetRef`, `city_lights: CityLights`. Semantyka dla shadera: światła pełne przy elewacji Słońca ≤ `on_below`, zero przy ≥ `on_below + fade_deg`, liniowo pomiędzy.
- `EarthAppearanceFacade.state(q: TimeQuery) -> EarthAppearance` (docstring: kąt obrotu z GMST; chmury dryfują z własnym `rate_deg_per_hour`). FEATURE: title „Wygląd Ziemi: rotacja, chmury, światła miast”, view SPACE, `state` frame.
- Example pins: `axial_tilt_deg 23.4393`; `rotation {100.6608, 15.041067}`; `clouds {texture {/textures/earth_clouds8K.jpg, 8192, 4096, "jpg"}, angle 42.0, rate 15.2, altitude 8.0}`; `subsolar_point (-23.01, -179.17)`; `day_texture /textures/earth_day8K.jpg` 8192×4096; `night_texture /textures/earrth_night8K.jpg` 8192×4096; `city_lights {on_below -6.0, fade 6.0}`, miasta (lat, lon, elev, on): Warszawa 52.2297 21.0122 −56.94 true; Stalowa Wola 50.5826 22.0532 −57.86 true; Nowy Jork 40.7128 −74.006 −25.94 true; Tokio 35.6762 139.6503 19.56 false; `meta.frame "EARTH_BODY_FIXED"`.

- [ ] **Step 1:** Utwórz moduł wg wzorca i pinów.
- [ ] **Step 2 (Verify):** wg wzorca; `curl -sf localhost:8000/health` → `"features":7`.
- [ ] **Step 3:** Commit: `git commit -m "feat(earth_appearance): rotation, clouds and city lights contracts"`

---

### Task 11: Frontend — powłoka i moduły core

**Files:**
- Create: `frontend/index.html`, `frontend/css/main.css`, `frontend/js/main.js`
- Create: `frontend/js/core/{units,clock,frame-scheduler,api-client,observer,scene,base-layer,layer-loader}.js`
- Create: `frontend/js/ui/{controls,layer-panel,inspector}.js`

**Interfaces:**
- Consumes: Task 3 (`/api/v1/features`, `/api/v1/frame`, ścieżki endpointów z manifestu).
- Produces:
  - `units.js`: `KM_PER_SCENE_UNIT = 1000`; `eclipticKmToScene({x, y, z}) -> [x/1000, z/1000, -y/1000]`; `latLonToScene(latDeg, lonDeg, radius) -> [x, y, z]` = to samo mapowanie osi zastosowane do `(cos φ cos λ, cos φ sin λ, sin φ)·r` (zgodne z UV `THREE.SphereGeometry`: lon 0 → +X, lon 90°E → −Z, biegun N → +Y); `altAzToScene(altDeg, azDeg) -> [cos h·sin A, sin h, −cos h·cos A]`
  - `clock.js`: `SIM_START = Date.UTC(2000,0,1)`, `SIM_END = Date.UTC(2100,0,1)`; `class SimulationClock extends EventTarget` — `constructor({t = Date.UTC(2026,0,1), speedHoursPerSecond = 1} = {})`, getter `t` (ms epoki), `playing`, `speedHoursPerSecond`, `play()`, `pause()`, `toggle()`, `seek(ms)` (clamp do zakresu), `tick(dtSeconds)` (nic gdy pauza; na końcu zakresu `t = SIM_END` i pauza); zdarzenia `timechange` (`CustomEvent`, `detail: {t, reason: "tick" | "seek"}`) i `playstatechange`
  - `observer.js`: `class ObserverState extends EventTarget` — `lat_deg = 0`, `lon_deg = 0`, `set(lat, lon)` (clamp, emituje `observerchange`)
  - `frame-scheduler.js`: `class FrameScheduler` — `constructor({api, clock, observer, getActiveKeys, dispatch, onError, minSimIntervalMs = 3_600_000, minRealIntervalMs = 250})`, `start()` (słucha `timechange` i `observerchange`), `refresh(reason) -> Promise<void>`; zasady: brak aktywnych kluczy → brak zapytania; `seek`/zmiana obserwatora → natychmiast; `tick` → gdy |t − ostatnio żądane t| ≥ `minSimIntervalMs` ORAZ od ostatniego zapytania ≥ `minRealIntervalMs` (maks. 4 zapytania/s przy każdej prędkości); nowe zapytanie przerywa poprzednie (`AbortController`); wynik o numerze sekwencji niższym niż ostatnio wysłany jest odrzucany; `dispatch(key, payload)` per payload, `onError(key, message)` per błąd
  - `api-client.js`: `class ApiError extends Error {status, detail}`; `class ApiClient` — `constructor(baseUrl = '/api/v1')`, `manifest()`, `getJson(path, params = {}, {signal} = {})` (ścieżka absolutna z manifestu; non-2xx → `ApiError`; odpowiedzi endpointów `static` cache'owane w `Map` po URL), `frame({t, lat_deg, lon_deg}, keys, {signal})` (`t` jako ISO string)
  - `scene.js`: `class SceneContext` — `constructor(container)`; `renderer` (`antialias`, `logarithmicDepthBuffer: true`, `pixelRatio = min(devicePixelRatio, 2)`), `camera` (fov 50, near 0.001, far 5000), `scene`, `controls` (OrbitControls), `sunLight` (`DirectionalLight`; kierunek ustawia warstwa `ephemeris`), `views: {space: Group, surface: Group}`; `setView(name)` (widoczność grup + preset kamery: space `pos [0,250,550] → [0,0,0]`, surface `pos [0,0,0.01] → [0,0,-1]`), `onFrame(cb: (dtSeconds) => void)`, `start()` (jedna pętla `requestAnimationFrame`, `ResizeObserver`); w `space` `AxesHelper(50)`
  - `base-layer.js`: `class BaseLayer` — `static id = ''`, `static view = 'space'`; `constructor(ctx)` gdzie `ctx = {api, scene, clock, observer, inspector, feature}`; `group` (`THREE.Group`); `data` (klucz → payload); `async init()` (no-op); `onData(key, payload)` (zapisuje w `data`, `inspector.show(key, payload)`); `update(tMs, dtSeconds)` (no-op); `setVisible(v)`; getter `visible`; `frameKeys()` (klucze endpointów z `frame: true` z `feature`); `dispose()` (usuwa grupę, zwalnia geometrie/materiały)
  - `layer-loader.js`: `loadLayers(manifest, ctx) -> Promise<BaseLayer[]>` — `import(feature.frontend_module)`, `default` musi mieć `id === feature.id` i `view === feature.view`; `await layer.init()`; `ctx.scene.views[feature.view].add(layer.group)`; błąd jednej warstwy → `inspector.error(feature.id, String(err))` i dalej
  - `inspector.js`: `class Inspector` — `constructor(root)`, `show(key, payload)` (`<details>` z `<pre>` JSON, ucięte do 20 000 znaków), `error(key, message)`
  - `layer-panel.js`: `renderLayerPanel(root, layers)` — checkbox na warstwę (etykieta `feature.title`, grupowane po `view`) → `layer.setVisible`
  - `controls.js`: `bindControls({clock, observer, scene})` — `#time-input` (UTC), `#time-slider` (zakres `SIM_START..SIM_END`, krok 3 600 000), `#play-btn`, `#speed-select` (1, 24, 168, 720 h/s), `#view-select` (`space` | `surface`), `#lat-input`, `#lon-input`; odświeżanie pól z `timechange` maks. raz na klatkę
  - `index.html`: importmap z Global Constraints; `<header>` z kontrolkami, `<main id="viewport">`, `<aside>` z `#layer-panel` i `#inspector`; `<script type="module" src="/js/main.js">`; `main.css`: ciemny motyw, grid header / viewport + aside, aside pod spodem na wąskich ekranach
  - `main.js` — `bootstrap()`: manifest → `SceneContext`, `SimulationClock`, `ObserverState`, `Inspector` → `loadLayers` → `Promise.allSettled` dla endpointów `static` (`layer.onData`) → `FrameScheduler` (`getActiveKeys` = `frameKeys()` widocznych warstw; `dispatch` po mapie klucz → warstwa; `onError` → `inspector.error`) → `start()` + `refresh('seek')` → `bindControls`, `renderLayerPanel` → `scene.onFrame(dt => { clock.tick(dt); layers.forEach(l => l.visible && l.update(clock.t, dt)); })` → `scene.start()`

- [ ] **Step 1:** Utwórz pliki wg Interfaces.
- [ ] **Step 2 (Verify):** `for f in frontend/js/**/*.js frontend/js/*.js; do node --check "$f"; done` (z `shopt -s globstar`) → brak błędów składni. Otwórz `http://localhost:8000/` → canvas z osiami, kontrolki w nagłówku, pusty panel warstw (warstw jeszcze nie ma — w inspektorze 7 błędów importu `layer.js`, co potwierdza, że loader nie wywraca aplikacji); konsola bez innych błędów.
- [ ] **Step 3:** Commit: `git commit -m "feat(frontend): app shell, core modules and ui"`

---

### Task 12: Warstwy-stuby, przewodnik dla zespołów, weryfikacja end-to-end

**Files:**
- Create: `frontend/js/features/{ephemeris,lagrange,moon_geography,moon_illumination,horizon,line_of_sight,earth_appearance}/layer.js`
- Create: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: Task 11 (`BaseLayer`, `units.js`, `ctx.scene.sunLight`).
- Każda warstwa: `export default class XLayer extends BaseLayer { static id = '<id>'; static view = '<view>'; }` + komentarz `TODO(zespół <id>)` z listą (jedna linia na punkt), bez kodu renderingu:
  - `ephemeris`: Ziemia w (0,0,0), Księżyc w `eclipticKmToScene(moon_km)`, `scene.sunLight` z `sun_km`; płynna animacja z `series` zamiast odpytywania co klatkę
  - `lagrange`: znaczniki L1–L5 z `position_km`, inny styl dla `stable`, opcjonalny widok w układzie rotującym z `rotating_frame`
  - `moon_geography`: najpierw `color_map_preview`, potem `color_map` (progresywnie), displacement z `height_map` gdy nie-null, etykiety z `latLonToScene(center)`
  - `moon_illumination`: `sun_dir_body` jako uniform shadera terenu, linia terminatora, wyróżnienie `in_shadow`
  - `horizon`: sylwetka horyzontu z `profile` (krok z payloadu), Ziemia/Słońce w `altAzToScene`, róża kierunków
  - `line_of_sight`: promień do Ziemi (zielony/czerwony wg `earth_visible`), HUD `clearance_deg`, oś czasu z `windows`
  - `earth_appearance`: kula z shaderem dzień/noc (`subsolar_point`, próg `on_below_sun_elevation_deg`, `fade_deg`), osobna sfera chmur o promieniu R+`altitude_km` obracana `clouds.angle_deg` niezależnie od `rotation.angle_deg`, znaczniki miast przełączane `lights_on`
- `docs/ARCHITECTURE.md` (PL): tabela modułów i właścicieli (z „Struktura plików”); „Dodaj funkcjonalność w 6 krokach” (folder backendu, `contract.py`, przykład JSON, `facade.py` ze stubem, `FEATURE`, `layer.js`) — bez edycji plików współdzielonych; przejście stub → obliczenia (zamień ciało metody, `meta.source = "computed"`, przykład zostaje jako dokumentacja i dalej musi przechodzić walidację przy starcie); konwencje (jednostki, układy, osie sceny, nazewnictwo, CSV w metrach, literówka `earrth`); zasady wydajności (dane czasowe tylko przez `/frame`, `static` raz, praca per piksel w shaderach, duże dane jako pliki statyczne + `AssetRef`, payloady kolumnowe, `series` do interpolacji po stronie klienta); uruchamianie (`docker compose up --build`, logi); gdzie oglądać kontrakty (`/docs`, `contracts/examples/`); jak sprawdzić, czy działa (kroki z „Weryfikacja end-to-end”).

- [ ] **Step 1:** Utwórz 7 warstw-stubów.
- [ ] **Step 2:** Napisz `docs/ARCHITECTURE.md`.
- [ ] **Step 3 (Verify backend):** `docker compose up -d --build` → `healthy`; `curl -sf localhost:8000/health` → `{"status":"ok","features":7}`; każdy endpoint z manifestu odpowiada 200:
  `curl -s $API/features | python3 -c "import sys,json; [print(e['path']) for f in json.load(sys.stdin)['features'] for e in f['endpoints']]" | while read p; do echo "$(curl -s -o /dev/null -w '%{http_code}' "localhost:8000$p?t=$T&start=$T&end=2026-01-01T02:00:00Z") $p"; done` → 10 linii `200`.
- [ ] **Step 4 (Verify zasoby, Review Focus #4):** `grep -ho '"/textures/[^"]*"' contracts/examples/*.json | sort -u | tr -d '"' | while read u; do echo "$(curl -sI -o /dev/null -w '%{http_code}' localhost:8000$u) $u"; done` → same `200` (w tym `earrth_night8K.jpg`).
- [ ] **Step 5 (Verify przeglądarka, Playwright MCP lub ręcznie) na `http://localhost:8000/`:** panel warstw z 7 pozycjami w grupach Space/Surface; inspektor zawiera `moon_geography.features`, `moon_geography.terrain` i 7 kluczy frame; konsola bez błędów; zmiana `#lat-input` → nowe `/api/v1/frame` z `lat_deg` (zakładka sieci); Play przy 24 h/s → maks. ~4 zapytania `/frame` na sekundę, szybkie przewijanie suwaka → poprzednie zapytania `canceled`; `#view-select = surface` ukrywa grupę space; odznaczenie warstwy usuwa jej klucze z kolejnych `/frame`. Odporność: tymczasowo zmień `static id` w jednej warstwie → pozostałe 6 działa, inspektor pokazuje błąd; cofnij.
- [ ] **Step 6:** Commit: `git commit -m "feat(frontend): stub layers for all features and architecture guide"`

---

## Weryfikacja end-to-end

1. `docker compose up --build` → kontener `healthy`; `GET /health` → `{"status":"ok","features":7}`.
2. `http://localhost:8000/docs` → 10 endpointów feature + `/api/v1/features` + `/api/v1/frame` z pełnymi schematami.
3. `curl "$API/frame?t=$T&lat_deg=10"` → 7 payloadów, `errors: {}`; `t=2101-01-01T00:00:00Z` → 422.
4. Task 12, kroki 3–5.

## Wykonanie

Rekomendacja: **Native** — zadania są sekwencyjne (każdy moduł używa nazw z Task 2–3), plan przypina pola i wartości, a bez testów subagent-reviewer per zadanie dodałby niewiele; na końcu jeden przegląd całej gałęzi. Jeśli wolisz Subagent-driven, napisz to przy akceptacji.
