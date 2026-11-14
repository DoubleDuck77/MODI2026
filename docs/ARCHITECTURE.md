# Architektura MODI 2026

Szkielet „contract-first”: każda funkcjonalność to osobny moduł z własnym kontraktem, fasadą
i warstwą frontu. Na start fasady zwracają przykładowe JSON-y z `contracts/examples/`.
Front i backend rozwijają się równolegle według tych samych plików.

```
przeglądarka (Three.js)                      FastAPI (Docker)
┌────────────────────────────┐   /api/v1/features   ┌───────────────────────────────┐
│ main.js → layer-loader     │ ───────────────────▶ │ registry: discover + walidacja│
│   └ features/<id>/layer.js │   /api/v1/<id>/<ep>  │   └ features/<id>/            │
│ FrameScheduler             │ ───────────────────▶ │       contract.py  (Pydantic) │
│   (1 zapytanie na klatkę)  │   /api/v1/frame      │       facade.py    (stub)     │
│ Inspector (podgląd JSON)   │ ◀─────────────────── │       __init__.py  (FEATURE)  │
└────────────────────────────┘   /textures/*        └──────────────┬────────────────┘
                                                                   │ from_example()
                                                     contracts/examples/<id>.<ep>.json
```

## Moduły i właściciele

| feature_id | widok | endpointy | backend | przykłady | front |
|---|---|---|---|---|---|
| `ephemeris` | space | `state` (frame), `series` | `backend/app/features/ephemeris/` | `ephemeris.*.json` | `frontend/js/features/ephemeris/` |
| `lagrange` | space | `points` (frame) | `backend/app/features/lagrange/` | `lagrange.points.json` | `frontend/js/features/lagrange/` |
| `moon_geography` | space | `features`, `terrain` (static) | `backend/app/features/moon_geography/` | `moon_geography.*.json` | `frontend/js/features/moon_geography/` |
| `moon_illumination` | space | `state` (frame) | `backend/app/features/moon_illumination/` | `moon_illumination.state.json` | `frontend/js/features/moon_illumination/` |
| `horizon` | surface | `view` (frame) | `backend/app/features/horizon/` | `horizon.view.json` | `frontend/js/features/horizon/` |
| `line_of_sight` | surface | `point` (frame), `windows` | `backend/app/features/line_of_sight/` | `line_of_sight.*.json` | `frontend/js/features/line_of_sight/` |
| `earth_appearance` | space | `state` (frame) | `backend/app/features/earth_appearance/` | `earth_appearance.state.json` | `frontend/js/features/earth_appearance/` |

Zespół pracuje tylko w swoich trzech miejscach. Pliki wspólne (`backend/app/core/`, `frontend/js/core/`,
`frontend/js/ui/`) zmieniamy rzadko i po uzgodnieniu.

## Dodaj funkcjonalność w 6 krokach

Bez edycji żadnego pliku współdzielonego:

1. `backend/app/features/<id>/` — nowy pakiet; nazwa folderu = `id` (`^[a-z][a-z0-9_]*$`).
2. `contract.py` — modele odpowiedzi dziedziczące `FeatureResponse` (pola z jednostką w nazwie: `_km`, `_deg`…);
   reguły spójności jako `model_validator(mode="after")`.
3. `contracts/examples/<id>.<endpoint>.json` — przykład z `meta` (`feature`, `endpoint`, `contract_version: "0.1.0"`,
   `source: "example"`, `frame`, `units`).
4. `facade.py` — `class XFacade(BaseFacade)`, `feature_id = "<id>"`, jedna metoda na endpoint,
   ciało `return self.from_example("<endpoint>", Model)` i docstring „Prawdziwa implementacja: …”.
5. `__init__.py` — `FEATURE = FeatureModule(id=..., title=..., view=View.SPACE|SURFACE, facade=..., endpoints=(Endpoint(...),))`.
   Endpoint `frame=True` musi mieć `params` z pól `ObserverQuery` (`t`, `lat_deg`, `lon_deg`);
   endpoint `TimeDependency.STATIC` nie ma `params`.
6. `frontend/js/features/<id>/layer.js` — `export default class extends BaseLayer { static id = '<id>'; static view = '...'; }`.

Backend przeładuje się sam (`--reload`). Moduł pojawi się w `/api/v1/features`, w `/docs` i w panelu warstw.
Jeśli przykład JSON nie pasuje do modelu, backend **nie wystartuje**, a w `docker compose logs api`
pojawi się `FeatureRegistryError` z nazwą pliku.

## Ze stuba do prawdziwych obliczeń

- Zamień ciało metody fasady na obliczenia i ustaw `meta.source = "computed"`.
- Wspólne dane bierz z providerów przez `self.ctx` (`ctx.ephemeris`, `ctx.terrain`;
  interfejsy w `backend/app/core/providers.py`). Nie odpytuj innych modułów przez HTTP.
- Przykład JSON zostaje jako dokumentacja kontraktu i dalej musi przechodzić walidację przy starcie.
- Zmiana kształtu kontraktu = zmiana `contract.py` + przykładu + `layer.js` w jednym commicie.

## Konwencje

- **Czas:** UTC, ISO 8601 (`2026-01-01T00:00:00Z`). Zakres danych: 2000-01-01T00:00Z … 2100-01-01T00:00Z,
  poza nim API zwraca 422. Czas bez strefy jest traktowany jako UTC.
- **Układy** (`meta.frame`): `ECLIPTIC_J2000_GEOCENTRIC` (jak JPL Horizons `500@399`, `ECLIPTIC`),
  `EARTH_MOON_ROTATING`, `MOON_BODY_FIXED`, `EARTH_BODY_FIXED`, `TOPOCENTRIC_HORIZON`.
- **Kąty:** stopnie; azymut od N zgodnie z ruchem wskazówek (E = 90°); długość wschodnia dodatnia.
- **Osie sceny** (`frontend/js/core/units.js`, jedyne miejsce przeliczeń): 1 jednostka = 1000 km;
  ekliptyka (x, y, z) → Three.js (x, z, −y); w widoku powierzchni N = −Z, E = +X, zenit = +Y.
- **`coords/*.csv` są w metrach**, mimo że `emphemeredis_downloader.py` ustawia `OUT_UNITS='KM-S'`
  (|moon| ≈ 3.61e8). Provider efemeryd dzieli przez 1000.
- **Tekstura nocy** to `Textures/earrth_night8K.jpg` (dwa „r” w nazwie pliku); kontrakt wskazuje rzeczywistą nazwę.

## Wydajność

- Dane zależne od czasu pobiera tylko `FrameScheduler`, jednym zapytaniem `/api/v1/frame` dla wszystkich
  widocznych warstw. Przy odtwarzaniu wysyła maks. ~4 zapytania/s (i nie częściej niż co godzinę czasu symulacji),
  przerywa poprzednie zapytanie i odrzuca spóźnione odpowiedzi.
- Endpointy `static` pobierane są raz przy starcie i cache'owane w kliencie.
- `update(t, dt)` warstwy działa co klatkę bez sieci. Między odpowiedziami interpoluj lub ekstrapoluj
  (np. kąty chmur z `rate_deg_per_hour`, pozycje z `ephemeris.series`).
- Praca per piksel (dzień/noc, światła miast, cienie terenu) należy do shaderów; backend podaje tylko parametry
  (kierunek Słońca, progi).
- Duże dane (tekstury, mapy wysokości) to pliki statyczne pod `/textures/…`, wskazywane w kontrakcie przez `AssetRef`.
  W JSON-ie nie przesyłamy obrazów.
- Szeregi czasowe są w formacie kolumnowym (`sun_km: [[x,y,z], …]`), maks. 2000 punktów na zapytanie.
- Fasady są bezstanowe i synchroniczne; FastAPI wykonuje je w threadpoolu, odpowiedzi idą przez GZip.

## Uruchamianie

```bash
docker compose up --build          # http://localhost:8000  (API: /api/v1, dokumentacja: /docs)
docker compose logs -f api         # logi, m.in. FeatureRegistryError przy złym przykładzie
```

Kod i JSON-y są podmontowane jako wolumeny, a backend przeładowuje się po zmianie `*.py` i `*.json`.
Przebudowa obrazu jest potrzebna tylko po zmianie `backend/requirements.txt`.
Bez Dockera: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`
(ścieżki domyślnie względem roota repo).

Kontrakty można oglądać w `/docs` (schematy OpenAPI generowane z Pydantic), w `contracts/examples/`
i na żywo w inspektorze na stronie.

## Jak sprawdzić, czy działa

```bash
T=2026-01-01T00:00:00Z; API=http://localhost:8000/api/v1
curl -s localhost:8000/health                                   # {"status":"ok","features":7}
curl -s "$API/frame?t=$T&lat_deg=10" | python3 -m json.tool     # 6 payloadów frame, errors: {}
curl -s -o /dev/null -w '%{http_code}\n' "$API/frame?t=2101-01-01T00:00:00Z"   # 422
# każdy endpoint z manifestu → 200
curl -s $API/features | python3 -c "import sys,json; [print(e['path']) for f in json.load(sys.stdin)['features'] for e in f['endpoints']]" \
  | while read p; do echo "$(curl -s -o /dev/null -w '%{http_code}' "localhost:8000$p?t=$T&start=$T&end=2026-01-01T02:00:00Z") $p"; done
# każdy zasób z kontraktów → 200
grep -ho '"/textures/[^"]*"' contracts/examples/*.json | sort -u | tr -d '"' \
  | while read u; do echo "$(curl -sI -o /dev/null -w '%{http_code}' localhost:8000$u) $u"; done
```

W przeglądarce: panel warstw pokazuje 7 pozycji, inspektor pokazuje payload każdego endpointu,
a zmiana czasu lub obserwatora wysyła jedno nowe `/api/v1/frame`.
