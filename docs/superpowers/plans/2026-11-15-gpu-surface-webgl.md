# Powierzchnia GPU (geografia.py → WebGL2) i zasoby w promieniu (radius.py) na FastAPI: plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Cel:** Tryb „Powierzchnia” na `/sim.html` staje się portem `geografia.py` (silnik PQS na GPU). Teren składa, przemieszcza i cieniuje GPU użytkownika w przeglądarce (WebGL2). Serwer bez GPU liczy tylko obserwatora (wysokość gruntu, nachylenie, horyzont), niebo i wydaje kafle DEM i albedo. Dochodzi trzeci tryb „Zasoby”: port `radius.py` (zasoby w promieniu R). Obliczenia są w FastAPI, a mapa i wykresy rysują się w przeglądarce.

**Architektura:**
- **Backend.** Moduł `lunar_surface` przechodzi z `newlunar.py` na `geografia.py`: endpointy `catalog`, `observer`, `sky`, `stars` plus binarne kafle `tiles/{dem|albedo}/{ty}/{tx}`. Endpoint `terrain` (siatka liczona na CPU serwera, do ~4.3 GB RAM) znika. Nowy moduł `lunar_resources` importuje `radius.py` i `generator.py`. Trasy binarne dostają mały hak `FeatureModule.extra_routes`.
- **Frontend, Powierzchnia.** Czysty WebGL2 bez three.js, bo oryginał liczy własną projekcję w shaderach. Shadery `geografia.py` są przepisane do GLSL ES 3.00 1:1. Quadtree LOD (`_lod_pass`, `_select_lod`) działa w JS co klatkę. Teren to instancjonowane paczki 64×64 z wysokością z tekstury DEM w vertex shaderze.
- **Kafle.** DEM 5760×2880 i albedo 8192×4096 dzielą się na siatkę 32×16 kafli po 11.25° (180×180 float32 i 256×256×3 uint8). Przeglądarka składa z nich teksturę-okno wokół obserwatora (promień `r_max`). Kafle są cache'owane przez HTTP.
- **Frontend, Zasoby.** Canvas 2D: mapa (PNG warstwy z backendu), kontur R, dwa wykresy słupkowe, sterowanie w DOM.

**Tech stack:** FastAPI 0.115.6, pydantic 2.10.4, numpy 2.2.1, numba 0.61.2. Nowe: scipy, matplotlib (Agg, z contourpy), Pillow, requests. WebGL2 (GLSL ES 3.00), vanilla ES modules, three.js 0.170.0 tylko w trybie Orbita.

**Spec:** Osobnego dokumentu nie ma. Wymagania pochodzą z prośby: „połączenie backendu, wyciągnięcie funkcjonalności do backendu FastAPI i podłączenie do frontendu, renderowanie przez GPU samego użytkownika w przeglądarce (WebGL), serwer nie ma GPU”. Decyzje użytkownika:
1. Źródłem jest `geografia.py` 1:1, z angielskimi napisami.
2. „WebGL, aby to się ładowało u klienta”, czyli wersja GPU **zastępuje** obecną Powierzchnię (port newlunar). Stary kod zostaje w historii gita.
3. Zakres: GPU i `radius.py`. „dwa wykresy.html” i `server.py` dostaną osobny plan.

Konwencje pochodzą z `docs/ARCHITECTURE.md`. W Tasku 1 kopiujemy ten plan do `docs/superpowers/plans/2026-11-15-gpu-surface-webgl.md`.

## Kontekst

- `geografia.py` (commit aadeeb2) to fork `actualgpu.py` („gpu final”). Rysuje przez OpenGL 3.3 (ctypes i pygame), więc na serwerze bez GPU nie ruszy.
  - Część liczącą da się zaimportować: `LunarTerrain3D(dem, albedo)` bez `gl`, `update_observer`, `get_topocentric_vectors` i pokrewne.
  - Część rysującą (`GPURenderer`, `_init_gpu`, `draw_3d`, `main`) trzeba przenieść do przeglądarki.
- Matematyka nieba (`get_topocentric_vectors`, `get_lunar_body_matrix`, `circle_overlap_fraction`, `horizon_visible_fraction`) ma ciała identyczne z newlunar. Obecna fasada `lunar_surface.sky` już ją odtwarza; zmienia się źródło obserwatora i teksty statusów.
- `geografia.py:1023` ma adnotację `-> pygame.Surface`, liczoną przy definicji, więc obecna atrapa pygame (pusty moduł) wywala import z `AttributeError`.
- `LunarTerrain3D.__init__` w geografii kondycjonuje DEM przy biegunach (`_condition_polar_dem`, kopia 66 MB). Kafle DEM muszą więc pochodzić z `terrain.dem`, a nie z surowego `.npy`.
- `update_observer` i metody, które woła (`geografia.py:1734-1956`), tylko przypisują atrybuty i nie piszą w miejscu do współdzielonych tablic. Dlatego `copy.copy(base)` na żądanie jest bezpieczne wątkowo bez locka.
- Funkcje `radius.py` i `generator.py` przyjmują ścieżki w argumentach: `load_base_albedo(path)`, `collect_resource_grids(cache_dir, albedo_gray)`, `LunarDepositAnalyzer(resources, w, h).query_roi(lat, lon, R)`. Podkład `moon_color.jpg` w roocie jest bajtowo identyczny z `Textures/moon_color.jpg` (sprawdzone `cmp`).
- `radius.py` importuje `matplotlib.pyplot` na poziomie modułu, a `generator.py` importuje `requests`, `PIL` i `scipy`. Żadnej z tych bibliotek nie ma w `backend/requirements.txt`.

## Global Constraints

- **Python:** Docker i `run_local.py` używają 3.12. Kod ma działać też na 3.10 (repo `venv/`): bez `datetime.UTC`, enumy jako `class X(str, Enum)`.
- **Root-skryptów nie edytujemy.** Dotyczy `geografia.py`, `radius.py`, `generator.py`, `neworb.py`, `newlunar.py`, `actualgpu.py` i `gpu.py`. Na końcu każdego taska `git diff --stat -- <te pliki>` ma być pusty.
- **Wierny port 1:1** z `geografia.py` i `radius.py`. Dotyczy stałych, LOD (`PATCH_N=64`, `TAU_PX=1.5`, `MAX_PATCHES=1024`, `MIN_CELL_SCALE=0.005`, głębokość 16, margines 90 px), wzorów w shaderach, kolejności rysowania, stanów GL, presetów, klawiszy, napisów HUD i statusów (po angielsku, jak w skryptach), formatów CSV oraz kolorów i tytułów wykresów. Fizyki ani modeli nie poprawiamy. Podejrzane błędy zgłaszamy użytkownikowi jednym zdaniem, bez zmian w kodzie.
- **Bez kopii fizyki w backendzie.** Fasady wołają funkcje skryptów. Dozwolone wyjątki:
  1. loader `year_data.load_year` (istnieje);
  2. formuły pętli nieba z `main()`, `geografia.py:2802-2834` (już są w fasadzie, w wersji newlunar);
  3. przygotowanie RGB nakładki z `radius.py:195-206`;
  4. wywołanie konturu z `radius.py:307-316` przez contourpy.
- **Kod renderujący** (shadery, LOD, HUD) przenosimy do JS i GLSL 1:1, z odnośnikiem `geografia.py:<linie>` w komentarzu nad każdym blokiem.
- **API:** tylko GET. JSON idzie przez `FeatureResponse` z przykładem w `contracts/examples/<feature>.<endpoint>.json`, walidowanym przy starcie, z `meta.source="computed"`. Dane binarne idą wyłącznie przez `FeatureModule.extra_routes`.
- **Frontend:** Powierzchnia to surowy WebGL2, bez three.js i bez bundlera. Orbita zostaje bez zmian.
- **Język:** identyfikatory po angielsku, docstringi i komentarze po polsku. Napisy z portowanych skryptów zostają po angielsku, a elementy strony (przyciski trybów, błędy, ładowanie) są po polsku.
- **Weryfikacja:** bez testów automatycznych i bez TDD (preferencja użytkownika). Każdy task kończy się uruchomieniem z curl, logami i przeglądarką.
- **Git:** branch `feat/gpu-surface` od bieżącego `feat/sim-page`. Trailer commita: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Odchylenia wymuszone przez przeglądarkę** (jedyne dozwolone):
1. **Okno z kafli.** DEM i albedo przychodzą kaflami 11.25° i są składane w teksturę-okno wokół obserwatora zamiast jednej globalnej tekstury 66 MB + 100 MB. Teren dalej niż `r_max` leży pod geometrycznym horyzontem i nie jest widoczny.
2. **Próbkowanie DEM.** Zamiast `texture()` na R32F z LINEAR używamy `texelFetch` i ręcznej interpolacji dwuliniowej o tej samej semantyce (S = REPEAT, T = CLAMP_TO_EDGE), bo filtrowanie liniowe R32F nie jest gwarantowane w WebGL2.
3. **Składnia shaderów.** `#version 300 es` z kwalifikatorami precyzji. Shader gwiazd ustawia `gl_PointSize = 1.0`.
4. **Linia horyzontu.** WebGL ignoruje `lineWidth > 1`, więc szerokość 2 px emulujemy 4 rysowaniami `LINE_STRIP` z przesunięciem 0/1 px.
5. **HUD i sterowanie.** HUD, etykiety „Sun”/„Earth” i kompas rysuje canvas 2D nad WebGL (bez tekstury HUD). Suwaki i przyciski są w DOM, z zakresami, domyślnymi wartościami i mapowaniami jak w skrypcie.
6. **CSV.** `C` pobiera `horizon.csv` w przeglądarce, a „Export CSV” w Zasobach pobiera plik. Nie ma auto-zapisu `lunar_roi_latest.csv`.
7. **Czas.** Używamy wspólnego `SimulationClock` strony (jak obecny port) zamiast startu rok 2000, indeks 0. Prędkość odtwarzania to dalej 24 h/s.
8. **Piksele.** Renderujemy w pikselach CSS (devicePixelRatio = 1), żeby progi w pikselach (`TAU_PX`, `r > 18 px`, gwiazdy 1 px) znaczyły to samo co w oknie pygame.
9. **Zasoby.** Mapa, pasek kolorów i wykresy to canvas 2D zamiast matplotlib, z tymi samymi kolorami, tytułami i etykietami. Kontur liczy backend algorytmem matplotliba (contourpy `mpl2014`).

## Review Focus

1. **Biegun.** Preset 3 Shackleton (−89.48, 129.80) i obserwator na lat 89.9. Okno obejmuje pełny pierścień długości (tekstura 8192 px szerokości). Nie ma dziur, NaN ani „wiatraczka” przy biegunie, a kafle pochodzą z kondycjonowanego DEM. Sprawdzają to Task 2 (krok 5) i Task 3 (krok 9).
2. **Antymeridian.** Obserwator na lon ±179.9: okno owija się przez szew, bez czarnego pasa i bez rozjechanych paczek po obu stronach. Sprawdzają to Task 2 (krok 5) i Task 3 (krok 9).
3. **Szybkie przesuwanie suwaków lat/lon/wysokości i zmiana presetu w trakcie ładowania kafli.** Spóźnione odpowiedzi `observer` i kafle nie trafiają do nowszego okna. Teren nie rysuje się w złym miejscu: do czasu gotowości okna jest ukryty, a HUD pokazuje ładowanie. Sprawdza to Task 3 (krok 9).
4. **Brak WebGL2, `MAX_TEXTURE_SIZE < 8192` albo utrata kontekstu.** Zamiast czarnego canvasa pojawia się czytelny komunikat w `#sim-error`, a Orbita dalej działa. Sprawdza to Task 3 (krok 9).
5. **Zasoby na krawędziach.** Pierwsze żądanie przed rozgrzaniem map daje 503 z `Retry-After`, a front ponawia. Promień 10 km z `pixel_count = 0` (ścieżka bilinear) oraz R = 1000 km przy biegunie i antymeridianie dają skończony JSON i kontur z wielu linii. Sprawdzają to Task 5 (krok 6) i Task 6 (krok 5).

---

### Task 1: Infrastruktura: atrapa pygame, trasy binarne, zależności, Docker

**Files:**
- Modify: `backend/app/core/legacy.py`, `backend/app/core/feature.py`, `backend/app/core/routing.py`, `backend/app/settings.py`
- Modify: `backend/requirements.txt`, `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml` (tylko wolumeny i env), `.dockerignore`, `run_local.py`
- Create: `docs/superpowers/plans/2026-11-15-gpu-surface-webgl.md` (kopia planu)

**Interfaces:**
- Produces:
  - `import_root_script(name, scripts_dir)`: sygnatura bez zmian. Atrapa `pygame` ma atrybut `Surface` (pusta klasa). Przed importem ustawia `os.environ.setdefault("MPLBACKEND", "Agg")`.
  - `FeatureModule.extra_routes: Optional[Callable[[BaseFacade], APIRouter]] = None`. `build_feature_router` dołącza `extra_routes(registry.facade(id))` pod prefiksem `/{id}` (czyli `/api/v1/{id}/…`) z `tags=[id]`. Tych tras nie ma w manifeście ani w `/frame` i nie mają przykładów.
  - `Settings.pds_data_dir: Path`: env `MODI_PDS_DATA_DIR`, domyślnie `REPO_ROOT / "lunar_pds_data"`.

- [ ] **Step 1:** `git switch -c feat/gpu-surface` i skopiuj plan do `docs/superpowers/plans/2026-11-15-gpu-surface-webgl.md`.
- [ ] **Step 2:** Zmień `legacy.py`: dodaj `Surface` do atrapy i ustaw `MPLBACKEND`. W docstringu dopisz powód: `geografia.py:1023`, adnotacja liczona przy `def`.
- [ ] **Step 3:** Dodaj pole `extra_routes` w `feature.py` (import `Callable`, `APIRouter`) i dołączanie w `routing.build_feature_router` (`routing.py:52-64`). Dopisz w docstringu `FeatureModule`, że to wyłącznie dla danych binarnych.
- [ ] **Step 4:** Dodaj `pds_data_dir` w `settings.py`, wzorem `coords_dir`.
- [ ] **Step 5:** Przypnij zależności: `scipy==1.15.2`, `matplotlib==3.10.1`, `pillow==11.1.0`, `requests==2.32.3`. Muszą to być wersje z kołami cp312 zgodne z numpy 2.2.1. Jeśli pip nie rozwiąże, weź najbliższe zgodne i zapisz je w commicie.
- [ ] **Step 6:** Podłącz Dockera i `run_local.py`:
  - `Dockerfile`: `COPY newlunar.py neworb.py geografia.py radius.py generator.py /srv/` (newlunar.py wypada w Tasku 2), `ENV MODI_PDS_DATA_DIR=/data/pds MPLCONFIGDIR=/tmp/matplotlib`.
  - `docker-compose.yml`: wolumeny `:ro` dla trzech nowych skryptów i `./lunar_pds_data:/data/pds:ro`. Ten sam wolumen danych w `docker-compose.prod.yml`.
  - `.dockerignore`: `lunar_pds_data`, `lunar_resource_maps`, `lunar_roi_exports`.
  - `run_local.py`: do `REQUIRED_DATA` dopisz `Textures/moon_color.jpg`, `lunar_pds_data/ironhd.txt` i `lunar_pds_data/thoriumhd.txt`.
- [ ] **Step 7: Weryfikacja.**
  1. `venv/bin/pip install -r backend/requirements.txt`.
  2. Import bez pygame:
     ```bash
     cd backend && ../venv/bin/python -c "import sys; sys.modules['pygame']=None; from app.core.legacy import import_root_script as i; from app.settings import REPO_ROOT as R; g=i('geografia',R); r=i('radius',R); print(g.LunarTerrain3D, r.LunarDepositAnalyzer)"
     ```
     Wpis `None` w `sys.modules` wymusza ścieżkę atrapy. Oczekiwane: dwie nazwy, bez wyjątku i bez okna.
  3. `docker compose build && docker compose run --rm api python -c "<to samo bez sys.modules, R=Path('/srv')>"` przechodzi.
  4. `curl -s localhost:8000/health` zwraca `{"status":"ok","features":9}`.
  5. `git diff --stat` dla root-skryptów jest pusty.
- [ ] **Step 8:** Commit `feat(backend): atrapa pygame.Surface, trasy binarne extra_routes, zależności radius/geografia`.

### Task 2: Backend `lunar_surface` na `geografia.py` (catalog, observer, sky, stars, kafle)

**Files:**
- Modify: `backend/app/features/lunar_surface/{__init__,contract,facade}.py`
- Create: `contracts/examples/lunar_surface.catalog.json`, `contracts/examples/lunar_surface.observer.json`
- Modify: `contracts/examples/lunar_surface.sky.json`
- Delete: `contracts/examples/lunar_surface.terrain.json`
- Modify: `Dockerfile`, `docker-compose.yml` (usuń `newlunar.py`)

**Interfaces:**
- Consumes: `extra_routes`, `import_root_script("geografia", …)`.
- Produces (używa Task 3 i 4):
  - `lunar_surface.catalog`, STATIC → `SurfaceCatalog{r_moon_km, dem_source, dem: TileSetInfo, albedo: TileSetInfo, albedo_is_u8, albedo_scale, patch_n, tau_px, max_patches, min_cell_scale}`.
    - `TileSetInfo{width, height, tile_w, tile_h, nx, ny, dtype: Literal["float32","uint8"], channels, url_template}`, gdzie `url_template = "/api/v1/lunar_surface/tiles/dem/{ty}/{tx}"` (dla albedo analogicznie).
    - Stałe LOD pochodzą z atrybutów klasy `geo.LunarTerrain3D`.
    - `albedo_scale` liczymy jak `_init_gpu` (`geografia.py:1643-1660`): 1.0 dla uint8, 0.40 dla float.
  - `lunar_surface.observer`, parametry `ObserverGeometryQuery(ObserverFields, EyeHeightField)` → `ObserverGeometry{observer, eye_height_m, observer_elevation_km, observer_radius_km, r_max_km, slope_deg, slope_dir, horizon: HorizonProfile}`.
    - `HorizonProfile` jak dotąd: 721 wpisów, `az_deg` od 0 do 360 włącznie.
  - `lunar_surface.sky`: kształt `LunarSky` bez zmian.
  - `lunar_surface.stars`: bez zmian.
  - `EyeHeightField.eye_height_m` dostaje domyślnie **15.0** (`ge=2, le=50000`), jak suwak w geografii.
  - Trasa binarna `GET /api/v1/lunar_surface/tiles/{layer}/{ty}/{tx}`:
    - `layer` ∈ {`dem`, `albedo`}, `0 ≤ ty < 16`, `0 ≤ tx < 32`; poza zakresem 404.
    - Treść: `dem` to 129 600 B float32 LE z `terrain.dem[ty*180:(ty+1)*180, tx*180:(tx+1)*180]`, `albedo` to 196 608 B uint8 RGB z `terrain.albedo_map` (kafle 256×256). Wiersz 0 to północna krawędź kafla.
    - Nagłówki: `Content-Type: application/octet-stream`, `Cache-Control: public, max-age=86400`.

- [ ] **Step 1: Kontrakt.** Usuń `TerrainQuery` i `LunarTerrainPatch`. Dodaj `TileSetInfo`, `SurfaceCatalog`, `ObserverGeometryQuery` i `ObserverGeometry`. Walidator `ObserverGeometry` sprawdza skończoność liczb.
- [ ] **Step 2: Fasada.**
  - `self.geo = import_root_script("geografia", …)`.
  - `_terrain()`: leniwie, pod jednym lockiem inicjalizacji, z mmapów v3 tworzy `geo.LunarTerrain3D(dem, color)` bez `gl`. Sprawdza podzielność 2880×5760 przez 180 i 4096×8192 przez 256; brak plików lub zły kształt daje 503.
  - `_observe(lat, lon, eye)`: LRU 64. Wykonuje `t = copy.copy(base)` i `t.update_observer(lat, lon, eye_height_m=eye)`, potem zapisuje potrzebne pola. Usuń `_terrain_locked`, `LOCK_TIMEOUT_S` i `_cell_albedo`.
  - `sky()` zostaje, ale bierze obserwatora z `_observe`. Teksty statusów kopiuje dosłownie z geografii, ze statusów w `main()` i z HUD (`geografia.py:2802-2834, 2951-2965`). Przedtem zrób diff formuł pętli z newlunar i przenieś każdą różnicę.
  - `stars()`: porównaj blok z `geografia.py:2602-2612`. Jeśli jest identyczny, zostaw bez zmian.
  - `tile_bytes(layer, ty, tx) -> bytes` plus `extra_routes`, które zwraca `Response(content, media_type=…, headers=…)`.
- [ ] **Step 3: Rejestracja.** W `__init__.py` są endpointy `catalog` (STATIC), `observer`, `sky`, `stars` (STATIC) oraz `extra_routes`. Opis wskazuje `/sim.html#surface` i `geografia.py`.
- [ ] **Step 4: Przykłady i Docker.** Wygeneruj przykłady wywołaniem fasady w Pythonie z `meta.source="example"`. Horyzont w przykładzie można skrócić do 8 wpisów. Usuń `newlunar.py` z `COPY` i wolumenów.
- [ ] **Step 5: Weryfikacja.** Najpierw `API=localhost:8000/api/v1`.
  1. `/health` zwraca `features: 9`. `curl -s $API/lunar_surface/catalog` pokazuje `dem.nx=32`, `ny=16`, `albedo_is_u8=true`.
  2. Zgodność ze skryptem:
     - `curl -s "$API/lunar_surface/observer?lat_deg=-43.31&lon_deg=-11.36"`;
     - jednolinijkowiec Pythona: `geografia.LunarTerrain3D(...).update_observer(-43.31,-11.36,15.0)`;
     - `observer_elevation_km`, `r_max_km`, `slope_deg`, `slope_dir` i `horizon.alt_deg[::90]` mają być identyczne.
  3. Krawędzie: obserwatorzy (−89.48, 129.8), (89.9, 0), (0.5, 179.9) i (0.5, −179.9) zwracają 200 i wartości skończone. Czas zimnego żądania (`-w %{time_total}`) wynosi poniżej 2 s. Cztery różne zapytania równolegle (`&` w bashu) dają cztery odpowiedzi 200.
  4. Kafle:
     - `curl -s $API/lunar_surface/tiles/dem/0/0 | wc -c` zwraca 129600, a albedo 196608;
     - `tiles/dem/16/0` i `tiles/xyz/0/0` zwracają 404 lub 422;
     - `curl -sI -H 'Accept-Encoding: gzip'` pokazuje `Cache-Control` i `content-encoding: gzip`;
     - bajty kafla DEM 14/5 są równe `terrain.dem[2520:2700, 900:1080].astype('<f4').tobytes()`.
  5. Niebo:
     - `sky?t=2025-03-14T06:58:00Z&lat_deg=0.67&lon_deg=23.47` (zaćmienie Księżyca, czyli Słońce zakryte przez Ziemię z Apollo 11): status Słońca zawiera `ECLIPSED`;
     - `t=2100-01-01T00:00:00Z` zwraca 200.
  6. RSS procesu uvicorn po krokach 2-5 wynosi poniżej ~800 MB (`ps -o rss`). Zapisz wartość.
  7. `git diff --stat` dla root-skryptów jest pusty.

  Tryb Powierzchnia na `/sim.html` jest do Tasku 3 zepsuty, bo brakuje `lunar_surface.terrain`. To oczekiwane.
- [ ] **Step 6:** Commit `feat(lunar_surface): geografia.py — observer, kafle DEM/albedo, niebo; bez siatki terenu na serwerze`.

### Task 3: Frontend WebGL2: teren z kafli (strona GPU `LunarTerrain3D`)

**Files:**
- Create: `frontend/js/sim/ui/slider.js` (przenieś `makeSlider` dosłownie z `frontend/js/sim/surface/surface-mode.js:47-86`)
- Create: `frontend/js/sim/surface/gl.js`, `shaders.js` (teraz tylko `TERRAIN_VS/FS`, `HORIZON_VS/FS`), `tile-window.js`, `terrain-renderer.js`
- Rewrite: `frontend/js/sim/surface/surface-mode.js`
- Modify: `frontend/css/sim.css` (canvas WebGL i nakładka 2D)

**Interfaces:**
- Consumes: `lunar_surface.catalog`, `.observer`, `.sky` i kafle z Tasku 2.
- Produces (używa Task 4):
  - `createProgram(gl, vsSrc, fsSrc) -> {program, u: Record<string, WebGLUniformLocation>, a: Record<string, number>}`. Błąd kompilacji wyrzuca wyjątek z logiem.
  - `class TileWindow`:
    - `constructor(gl, tileset, {internalFormat, format, type, mipmaps, unit})`;
    - `selectTiles(latDeg, lonDeg, rMaxKm) -> {ty0, ty1, tx0, nTx, fullRing}`;
    - `async ensure(latDeg, lonDeg, rMaxKm, signal) -> boolean`;
    - `ready: boolean`, `texture: WebGLTexture`;
    - `uniforms() -> {origin: [x0, y0], size: [ww, wh], full: 0|1}`.
  - `class TerrainRenderer`:
    - `constructor(gl, catalog)`, `setObserver(geom)`;
    - `cameraBody(camAlt, camAz)`, `selectLod(cw, ch, camAlt, camAz, fov)`;
    - `draw(params)`, gdzie `params = {cw, ch, camAlt, camAz, fov, sunAlt, sunAz, earthAlt, earthAz, sunEffectiveVis, eclipseRedGlow, wireframe, showHorizonLine, demWin, albedoWin}`;
    - pola `drawnCount`, `nTris`, `lodTauUsed`.
  - `createSurfaceMode({root, api, endpoint, clock}) -> {activate(), deactivate()}`: sygnatura bez zmian.

- [ ] **Step 1: Kontekst.**
  - `getContext('webgl2', {depth: true, alpha: false, antialias: <jak atrybuty pygame w geografia.py:2550-2558>})`.
  - Canvas ma `width = clientWidth`, `height = clientHeight` (DPR 1), z przeliczeniem przy `resize`.
  - Błędy idą do `#sim-error`:
    - brak WebGL2: „Tryb Powierzchnia wymaga WebGL2 — ta przeglądarka go nie obsługuje.”;
    - `MAX_TEXTURE_SIZE < 8192`: „GPU obsługuje tekstury do N px, teren wymaga 8192 px.”;
    - `webglcontextlost`: „Utracono kontekst WebGL — odśwież stronę.”
- [ ] **Step 2: `tile-window.js`.**
  - Kafel ma 11.25° w obu zbiorach. Promień okna to `θ = rMaxKm / r_moon_km + 4·π/2880` (4 teksele DEM zapasu).
    ```
    latMin = lat − θ°, latMax = lat + θ°
    fullRing = latMax ≥ 90 || latMin ≤ −90 || sin θ ≥ cos lat
    dLon = fullRing ? 180 : asin(sin θ / cos lat)°
    ty0 = clamp(floor((90 − latMax)/11.25), 0, 15),  ty1 = clamp(floor((90 − latMin)/11.25), 0, 15)
    tx0 = floor((lon − dLon + 180)/11.25),  tx1 = floor((lon + dLon + 180)/11.25)
    nTx = tx1 − tx0 + 1;  if (nTx ≥ 32 || fullRing) { tx0 = 0; nTx = 32 }
    kafel i: tx = ((tx0 + i) mod 32 + 32) mod 32, w oknie na kolumnie i·tile_w
    ```
  - Tekstura okna:
    - DEM: `R32F/RED/FLOAT`, NEAREST.
    - Albedo: `RGB8/RGB/UNSIGNED_BYTE`, `UNPACK_ALIGNMENT=1`, MIN = `LINEAR_MIPMAP_LINEAR`, MAG = `LINEAR`, T = `CLAMP_TO_EDGE`, S = `REPEAT` przy pełnym pierścieniu, inaczej `CLAMP_TO_EDGE`. Po wgraniu wszystkich kafli `generateMipmap`.
  - Kafle trafiają przez `texSubImage2D` w miejsce w oknie. Mapa `url → ArrayBuffer` działa jako LRU na 160 kafli i ponownie wykorzystuje bajty.
  - `ensure` z nowszym wywołaniem unieważnia starsze, przez licznik generacji i AbortSignal.
- [ ] **Step 3: `shaders.js`.**
  - `_TERRAIN_VS/FS` (`geografia.py:1223-1462`) i `_HORIZON_VS/FS` (`:1464-1486`) przepisujemy dosłownie. Zmieniają się tylko:
    1. nagłówek `#version 300 es`, `precision highp float; precision highp int; precision highp sampler2D;`;
    2. dostęp do DEM;
    3. UV albedo, przez `albedoUV(uv)` przed `texture(u_tex_albedo, …)`;
    4. uniform `u_offset_px` w horizon VS (`gl_Position.xy += u_offset_px * 2.0 / u_viewport * gl_Position.w`).
  - Wspólny kod GLSL dla terenu (wklejony do VS i FS):
    ```glsl
    uniform vec2 u_dem_origin, u_dem_win; uniform int u_dem_full;      // okno DEM w tekselach globalnych
    uniform vec2 u_alb_origin, u_alb_win, u_alb_size;
    float demTexel(ivec2 g) {                                             // = GL REPEAT (S), CLAMP_TO_EDGE (T)
      int W = int(u_dem_size.x), H = int(u_dem_size.y);
      int gx = ((g.x % W) + W) % W, gy = clamp(g.y, 0, H - 1);
      int lx = u_dem_full == 1 ? gx : clamp(((gx - int(u_dem_origin.x)) % W + W) % W, 0, int(u_dem_win.x) - 1);
      int ly = clamp(gy - int(u_dem_origin.y), 0, int(u_dem_win.y) - 1);
      return texelFetch(u_tex_dem, ivec2(lx, ly), 0).r;
    }
    float demLinear(vec2 uv) {                                            // = texture() z LINEAR
      vec2 t = uv * u_dem_size - 0.5; vec2 i = floor(t); vec2 f = t - i; ivec2 b = ivec2(i);
      return mix(mix(demTexel(b), demTexel(b + ivec2(1,0)), f.x),
                 mix(demTexel(b + ivec2(0,1)), demTexel(b + ivec2(1,1)), f.x), f.y);
    }
    vec2 albedoUV(vec2 uv) {
      return vec2(mod(uv.x * u_alb_size.x - u_alb_origin.x, u_alb_size.x) / u_alb_win.x,
                  (uv.y * u_alb_size.y - u_alb_origin.y) / u_alb_win.y);
    }
    ```
  - Zamiana wywołań `texture(u_tex_dem, …)`:
    - W `sample_dem_catmull` w VS każde `texture(u_tex_dem, ((i + k) * inv_sz))` trafia w środek teksela, więc staje się `demTexel(ivec2(floor(texel)) + ivec2(kx, ry))` z tymi samymi offsetami −1..2.
    - We FS każde `texture(u_tex_dem, smooth_dem_uv(x)).r` staje się `demLinear(smooth_dem_uv(x))`.
- [ ] **Step 4: `terrain-renderer.js`.**
  - Te metody przenosimy 1:1 z arytmetyką w Float64: `_build_static_patch_geometry` (`:1579`), `_camera_body` (`:1996`), `_lod_pass` (`:2004-2115`) i `_select_lod` (`:2117-2139`, ze stanem histerezy `lodTau`).
  - Bufor instancji to `Float32Array(MAX_PATCHES·5)` z dzielnikiem 1. Atrybuty: `in_lat_lon` vec4 i `in_skirt_km`.
  - `draw` odtwarza `draw_3d` (`:2141-2270`):
    - near 0.00005, far `max(2000, 2·r_max)`;
    - `DEPTH_TEST`, `CULL_FACE`, CCW, bez blendingu;
    - drut (wireframe) z `polygonOffset(1,1)`, potem `LINES` z `u_wire_add = (35,35,40)/255`;
    - indeksy `UNSIGNED_INT`;
    - linia horyzontu z 721 punktów, bez depth, w 4 przejściach z offsetem (0,0), (1,0), (0,1), (1,1) px.
  - Dla jednostki DEM ustawiamy uniformy okna z `demWin.uniforms()`, dla albedo z `albedoWin.uniforms()`, plus `u_alb_size = (8192, 4096)`.
- [ ] **Step 5: `surface-mode.js`, kamera i dane.**
  - Stan kamery jak `main()`:
    - `cam_az = 15°`, `cam_alt = max(14°, hor(cam_az) + 6°)` po pierwszym observerze;
    - FOV 75° (zakres 0.2°–115°), wygładzanie `fov += (target − fov)·min(1, 14·dt)`;
    - `zoom_at_point` (`:2622-2640`), przeciąganie (`:2720-2726`), kółko ×0.8, `+`/`=`/`-` oraz `R`.
  - Dane:
    - `catalog` z `cache: true`;
    - `observer`: debounce 250 ms, AbortController, licznik generacji; po odpowiedzi `TileWindow.ensure` dla DEM i albedo;
    - `sky`: przenieś obecny mechanizm z `surface-mode.js:234-331` (jedno żądanie w locie, ≥200 ms, `skyAt` z interpolacją, rotacja osi Ziemi z `:264-283`).
  - Teren rysuje się tylko wtedy, gdy oba okna są gotowe dla bieżącej generacji obserwatora. W przeciwnym razie nakładka pokazuje „Ładowanie kafli terenu k/n”.
  - `root._debug` wystawia `{drawnCount, nTris, lodTauUsed, tiles, fps, observer}`.
- [ ] **Step 6:** Kolejność w pętli `requestAnimationFrame`: clear `(5,7,12)/255` → teren → horyzont. Niebo dochodzi w Tasku 4. `deactivate()` zatrzymuje rAF i nasłuchy, a ponowna aktywacja używa tego samego kontekstu.
- [ ] **Step 7:** Usuń z `surface-mode.js` wszystkie importy three.js. Pliki `terrain-mesh.js` i `sky-bodies.js` zostają do Tasku 4, ale nikt ich już nie importuje.
- [ ] **Step 8:** Ręczne uruchomienie: `docker compose up` i `http://localhost:8000/sim.html#surface`. Okno przeglądarki ustaw tak, żeby canvas miał 1280×800.
- [ ] **Step 9: Weryfikacja.**
  1. Teren Tycho jest widoczny, konsola bez błędów, a `root._debug.drawnCount` jest większe od 0.
  2. Lokalnie `venv/bin/python geografia.py` (pygame, GPU dewelopera) w tej samej lokacji i kierunku. Na zrzutach obok siebie sylwetki terenu i linia horyzontu się pokrywają, a liczba paczek mieści się w ±10% wartości z HUD pygame.
  3. Krawędzie: preset 3 (biegun), lat 89.9 oraz lon 179.9 i −179.9 nie mają dziur ani szwów (`root._debug.tiles` pokazuje pełny pierścień i owinięcie). `M` pokazuje siatkę.
  4. Szybkie przesuwanie lat w DevTools Network: stare żądania są `canceled`, a teren nigdy nie pojawia się w złym miejscu.
  5. Komunikaty błędów:
     - w konsoli `HTMLCanvasElement.prototype.getContext = () => null` przed pierwszym wejściem w `#surface`, potem przełącz tryb: widać komunikat o WebGL2, a `#orbit` działa;
     - `gl.getExtension('WEBGL_lose_context').loseContext()`: widać komunikat o utracie kontekstu.
  6. Zapisz `root._debug.fps` w widoku domyślnym. Nie strojemy niczego, stałe zostają 1:1.
- [ ] **Step 10:** Commit `feat(sim): Powierzchnia na WebGL2 — teren PQS z geografia.py z kafli DEM/albedo`.

### Task 4: Frontend: niebo GPU, HUD, sterowanie, czas, CSV

**Files:**
- Modify: `frontend/js/sim/surface/shaders.js` (dochodzą `STAR_VS/FS`, `GRID_VS/FS`, `QUAD_VS`, `SUN_FS`, `EARTH_FS`), `frontend/js/sim/surface/surface-mode.js`
- Create: `frontend/js/sim/surface/sky-renderer.js`, `frontend/js/sim/surface/hud.js`
- Delete: `frontend/js/sim/surface/terrain-mesh.js`, `frontend/js/sim/surface/sky-bodies.js`

**Interfaces:**
- Consumes: Task 3 (`createProgram`, `TerrainRenderer`, `makeSlider`), `lunar_surface.stars`, `LunarSky`.
- Produces:
  - `class SkyRenderer`:
    - `constructor(gl, stars)`, `async loadEarthTextures()`;
    - `drawStars(view)`, `drawGrid(view)`;
    - `drawTelescopicSun(view, sun)`, `drawTelescopicEarth(view, earth, sky)`.
  - Funkcje HUD:
    - `drawHud(ctx, lines, {panelW: 675})`;
    - `drawBodyLabel(ctx, text, x, y, rgb)`;
    - `drawCompass(ctx, view, horizonAt)`.

- [ ] **Step 1: Shadery nieba.** `_STAR_*`, `_GRID_*`, `_QUAD_VS`, `_SUN_FS` i `_EARTH_FS` (`geografia.py:527-834`) przepisujemy dosłownie, z tymi samymi zmianami nagłówka co w Tasku 3. `gl_FragCoord` w WebGL ma ten sam początek (lewy dolny róg), więc `py = u_ch − gl_FragCoord.y − 0.5` zostaje.
- [ ] **Step 2: `sky-renderer.js`**, port `GPURenderer` (`:846-1205`):
  - Bufory gwiazd (stride 16) i siatki: okręgi alt 0/30/60°, krok 5°.
  - Quady Słońca i Ziemi, wzory rozmiaru i halo z `draw_telescopic_sun` i `draw_telescopic_earth`, w tym ramka tarczy liczona na CPU i `night_lod`.
  - Tekstury to dokładnie te pliki, które ładuje `load_earth_textures`: `/textures/earth_day8K.jpg`, `/textures/earth_night.jpg` (geografia nie znajduje `earrth_night8K.jpg`, bo w nazwie jest literówka) i `/textures/earth_clouds8K.jpg` (kanał 0 jako R8).
    - Parametry tekstur jak w `GPURenderer.__init__`.
    - Mipy nocy liczy CPU według `build_night_mipmaps` (0.45·mean + 0.55·max), z `TEXTURE_MAX_LEVEL`. Przenieś `buildNightMips` z `sky-bodies.js:183-221`, jeśli jest równoważny; inaczej przepisz z Pythona.
    - Dekodowanie: `createImageBitmap` → canvas → `getImageData`.
  - Gwiazdy: ustaw `u_R_body = ecliptic_to_enu` z `LunarSky`, a `u_north/east/up` jako osie (1,0,0), (0,1,0), (0,0,1). Wektory kamery są w ENU. Iloczyny skalarne są niezmiennicze, więc wynik jest ten sam co z `R_body` i bazą w układzie ciała. W `uniformMatrix3fv(loc, false, …)` podaj macierz kolumnami, tak jak `R_body.T` w `draw_stars`.
  - Przesunięcie chmur `cloud_offset` i animacja czasu liczą się jak w obecnym porcie (ta sama formuła z newlunar i geografii).
- [ ] **Step 3: Kolejność i stany** jak `main()` (`geografia.py:2840-2990`): clear → gwiazdy → siatka → Słońce → Ziemia (bez depth, blend `SRC_ALPHA, ONE_MINUS_SRC_ALPHA`) → teren i horyzont → HUD.
- [ ] **Step 4: HUD (`hud.js`)** na canvasie 2D nad WebGL:
  - Linie dosłownie z `geografia.py:2951-2965`: Terrain, Slope, Zoom, GPU mesh, statusy EARTH i SUN, pomoc.
  - Panel: prawy górny róg, szerokość 675, tło `rgba(15,20,30,195/255)`, odstęp 20 px, font `15px Consolas, "DejaVu Sans Mono", monospace` i bold 18.
  - Etykiety „Sun” i „Earth” w kolorach ze skryptu oraz kompas N…NW na wysokości `horyzont + max(1.2°, 0.02·fov)`.
  - Komunikat statusu (np. po `C`) znika po 3.5 s.
- [ ] **Step 5: Sterowanie.**
  - Suwaki DOM (`ui/slider.js`) z etykietami, zakresami, krzywą potęgową i formatami z `geografia.py:2591-2595`: Year, Time of Year, Latitude, Longitude, Height Above Surface. Ruch lat/lon ustawia nazwę lokacji jak w skrypcie.
  - Klawisze z `geografia.py:2726-2770`: Space, `+`, `=`, `-`, keypad, R, E, S (drugie naciśnięcie zoomuje do 3.2° lub 1.4°), L (8°), M, H, C, 1-5.
  - Presety z `geografia.py:2673-2679` jako stała JS z odnośnikiem. Po odpowiedzi `observer` ustawiają `cam_az = preset_az`, `cam_alt = min(π/2 − 0.05, hor + 5.5°)`.
  - Czas: wspólny `clock`, Space przełącza odtwarzanie, 24 h/s, zawijanie w roku jak obecny port.
- [ ] **Step 6: `C`.** Pobiera `horizon.csv` z 12 kolumnami i formatami `export_horizon_csv` (`:1961-1994`): 720 wierszy (`idx < n_az`) z ostatniej odpowiedzi `observer`.
- [ ] **Step 7:** Usuń `terrain-mesh.js` i `sky-bodies.js`. `grep -rn "three" frontend/js/sim/surface` ma być pusty.
- [ ] **Step 8: Weryfikacja** obok `venv/bin/python geografia.py` (czas ustawiony suwakami Year i Time of Year na tę samą godzinę):
  1. Tycho, dowolna data ze Słońcem nad horyzontem: niebo, gwiazdy, siatka i kompas się pokrywają, a HUD ma te same wartości do ostatniej cyfry: Terrain, Slope, Earth/Sun Alt/Az.
  2. Apollo 11, `2025-03-14T06:58Z`: HUD pokazuje `ECLIPSED`, teren ma czerwonawy odcień, a `S` dwa razy pokazuje Słońce z halo.
  3. `E` dwa razy: Ziemia teleskopowa z chmurami, światłami nocnymi i terminatorem zgodna ze zrzutem pygame.
  4. Wszystkie klawisze i suwaki działają. CSV ma 12 kolumn i 720 wierszy, a wartości zgadzają się z `/observer`.
  5. Przełączanie Powierzchnia ↔ Orbita 10 razy: brak błędów i spadku FPS (jeden kontekst, rAF zatrzymany w nieaktywnym trybie).
- [ ] **Step 9:** Commit `feat(sim): niebo GPU, HUD i sterowanie z geografia.py; usunięty port newlunar (three.js)`.

### Task 5: Backend `lunar_resources` (radius.py i generator.py)

**Files:**
- Create: `backend/app/features/lunar_resources/{__init__,contract,facade}.py`
- Create: `contracts/examples/lunar_resources.catalog.json`, `contracts/examples/lunar_resources.roi.json`
- Create: `frontend/js/features/lunar_resources/layer.js` (zaślepka jak `frontend/js/features/lunar_orbit/layer.js`)

**Interfaces:**
- Consumes: `Settings.pds_data_dir`, `extra_routes`, `import_root_script("radius")` (sam importuje `generator`).
- Produces (używa Task 6):
  - `lunar_resources.catalog`, STATIC → `ResourceCatalog`:
    - `map_width`, `map_height`, `r_moon_km`;
    - `layers: List[ResourceLayer]`, gdzie `ResourceLayer{key, title, unit, cmap, vmin, vmax, colormap_u8: List[Tuple[int,int,int]]` (dokładnie 256), `global_mean: Optional[float], data_source, image_url}`;
    - `chart_groups: List[{title, unit, keys}]`;
    - `defaults{lat_deg: 20, lon_deg: -25, radius_km: 250}`;
    - `sliders`: zakresy i kroki z `radius.py`.
  - `lunar_resources.roi`, parametry `RoiQuery(ObserverFields)` plus `radius_km: Field(gt=0, le=5458)` → `ResourceRoi`:
    - `roi: {lat_deg, lon_deg, radius_km, cap_area_km2, pixel_count}`;
    - `rows: List[RoiRow]` z polami o **tych samych nazwach i w tej samej kolejności** co słowniki z `query_roi` (`radius.py:146-160`), przy czym NaN zamieniamy na `None`;
    - `contour_lonlat: List[List[Tuple[float,float]]]`.
  - Trasa binarna `GET /api/v1/lunar_resources/layers/{key}.png`: PNG RGB 1024×512 nakładki, nieznany klucz daje 404, `Cache-Control: public, max-age=86400`.

- [ ] **Step 1: Kontrakt** z walidatorami: `colormap_u8` ma długość 256, `rows` ≤ 10, punkty konturu są skończone.
- [ ] **Step 2: Fasada.**
  - `__init__` startuje wątek-demon `_build()`:
    1. `gray, w, h = gen.load_base_albedo(settings.textures_dir / "moon_color.jpg")`;
    2. `resources = gen.collect_resource_grids(settings.pds_data_dir, gray)`;
    3. `self.analyzer = rad.LunarDepositAnalyzer(resources, w, h)`;
    4. dla każdego klucza z `MAP_LAYER_KEYS`, który jest dostępny, liczymy `(rgb, vmin, vmax)` jak `radius.py:195-206` i PNG przez Pillow z `np.round(rgb·255)` w uint8;
    5. na końcu log `[lunar_resources] gotowe w X s`.
  - Wyjątek z `_build()` zapisujemy i potem zwracamy jako 503 z treścią. `discover_and_download_pds_files` **nie** wołamy: serwer nie chodzi do sieci, a brak plików daje 503 z listą.
  - `_require()` przed zakończeniem budowy zwraca 503 z `Retry-After: 5`.
  - `catalog()`:
    - `colormap_u8` = `plt.get_cmap(name)(np.arange(cmap.N))[:, :3]·255`, zaokrąglone. To dokładne, bo `cmap(float)` w matplotlib wybiera jeden z `N = 256` kolorów.
    - Tytuły, jednostki i cmapy z `ENGLISH_RESOURCE_SPECS`, grupy z `CHART_GROUPS`.
  - `roi(q)`:
    - `query_roi`, potem `dist = analyzer.spherical_distance_km(...)`;
    - jeśli `nanmin < R < nanmax`, kontur to `contourpy.contour_generator(x=lon_grid, y=lat_grid, z=dist, name=rcParams["contour.algorithm"], corner_mask=rcParams["contour.corner_mask"]).lines(R)`, czyli ta sama ścieżka co `ax_map.contour` w `radius.py:307-316`;
    - w przeciwnym razie `[]`.
- [ ] **Step 3:** Rejestracja (`view=View.SURFACE`, opis wskazuje `/sim.html#resources`), przykłady wygenerowane z fasady (`source="example"`) i zaślepka `layer.js`.
- [ ] **Step 4:** Uruchom backend i sprawdź `/health`: `features: 10`.
- [ ] **Step 5: Zgodność ze skryptem.** Uruchom `.venv/bin/python radius.py --no-gui --csv <scratchpad>/roi.csv` (z roota, w venv z nowymi zależnościami). Każda wartość z `curl -s "$API/lunar_resources/roi?lat_deg=20&lon_deg=-25&radius_km=250"` ma być identyczna z CSV.
- [ ] **Step 6: Weryfikacja krawędzi.**
  1. Zaraz po starcie `roi` zwraca 503 z `Retry-After`, a po logu „gotowe” zwraca 200. Zapisz czas budowy i szczytowy RSS (`docker stats` albo `/usr/bin/time -v`).
  2. `radius_km=10` w (0.25, 0.25) daje 200, skończone wartości, `pixel_count` może być 0.
  3. `radius_km=1000` w (85, 179) daje 200 i co najmniej jedną linię konturu.
  4. `radius_km=0` daje 422.
  5. `layers/FeO.png` otwarty w PIL ma rozmiar (1024, 512); `layers/XYZ.png` daje 404.
  6. `git diff --stat` dla root-skryptów jest pusty.
- [ ] **Step 7:** Commit `feat(lunar_resources): radius.py na FastAPI — ROI, kontur, warstwy PNG`.

### Task 6: Frontend, tryb „Zasoby” na `/sim.html`

**Files:**
- Modify: `frontend/sim.html` (przycisk `#mode-resources` „Zasoby”, sekcja `#mode-resources-root`), `frontend/js/sim/main.js` (`MODES.resources`, hash `#resources`), `frontend/css/sim.css`
- Create: `frontend/js/sim/resources/resources-mode.js`, `frontend/js/sim/resources/resource-charts.js`

**Interfaces:**
- Consumes: `lunar_resources.catalog`, `.roi`, `layers/{key}.png`, `makeSlider`.
- Produces:
  - `createResourcesMode({root, api, endpoint, clock}) -> {activate, deactivate}` (zegar nieużywany);
  - `drawBarChart(ctx, group, rows)`.

- [ ] **Step 1: Układ** odwzorowuje figurę `radius.py:207-330`:
  - mapa po lewej, dwa wykresy po prawej, suwaki na dole, „Map Overlay” po lewej, dwa przyciski;
  - kolory: tło figury `#12151a`, osie `#181c23`, teksty `#c9d1d9`/`#e6edf3`, znacznik i kontur `#00f5d4` (1.8 px), status `#7ee787`.
- [ ] **Step 2: Mapa (canvas).**
  - PNG warstwy, cache'owany per klucz, rozciągnięty na −180..180 × −90..90.
  - Podziałka co 30°, podpisy osi i tytuł dosłownie z `radius.py`, znacznik „+”, polilinie `contour_lonlat`.
  - Pasek kolorów z `colormap_u8` od vmin do vmax, z podpisem `Active Layer: {title} [{unit}]`.
- [ ] **Step 3: Wykresy** (`resource-charts.js`): dwa poziome wykresy słupkowe według `chart_groups` (ROI kontra globalnie). Etykiety `{v:.2f} {unit} ({rel:+.0f}%)`, tytuły, kolejność i kolory z `radius.py:332-385`.
- [ ] **Step 4: Sterowanie.**
  - Suwaki Latitude, Longitude i Radius R (zakresy i kroki z `catalog.sliders`), radio „Map Overlay”, „Export CSV”, „Reset (Imbrium)” (20, −25, 250), klik w mapę jak `radius.py:393-404`.
  - `roi`: debounce 150 ms, AbortController, licznik generacji. Na 503 nakładka „Przygotowywanie map zasobów (NASA PDS)…” i ponowienie po `Retry-After`.
  - Export CSV:
    - nagłówek z kluczy `rows[0]` w kolejności, BOM UTF-8, przecinek;
    - nazwa `lunar_roi_lat{lat:+.1f}_lon{lon:+.1f}_R{R:.0f}km.csv` (`radius.py:408`);
    - status `Exported CSV: <nazwa>`.
- [ ] **Step 5: Weryfikacja** obok `.venv/bin/python radius.py` (GUI matplotlib):
  1. Widok domyślny i po kliknięciu w trzy punkty, w tym biegun i antymeridian przy R = 1000: liczby, kształt konturu, tytuł i słupki się zgadzają.
  2. Przełączenie wszystkich 10 warstw daje ten sam wygląd i pasek kolorów.
  3. Eksportowany CSV po znormalizowaniu końców linii jest identyczny z wynikiem `radius.py --csv` dla tych samych parametrów (`diff`).
  4. Pierwsze wejście tuż po starcie serwera pokazuje nakładkę i samo się odświeża.
  5. Przełączanie wszystkich trzech trybów działa bez błędów w konsoli.
- [ ] **Step 6:** Commit `feat(sim): tryb Zasoby — port radius.py (mapa, kontur R, wykresy, eksport CSV)`.

### Task 7: Dokumentacja, limity prod, weryfikacja końcowa

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `docker-compose.prod.yml` (`mem_limit` i komentarz)

- [ ] **Step 1: `ARCHITECTURE.md`.**
  - Tabela modułów: `lunar_surface` (geografia: `catalog`, `observer`, `sky`, `stars` plus kafle) i `lunar_resources`.
  - Nowa sekcja „Trasy binarne (`extra_routes`)”.
  - Przepisana sekcja `/sim.html`:
    - Powierzchnia: geografia.py w WebGL2, kafle, podział na pracę serwera i GPU klienta, lista odchyleń;
    - Zasoby;
    - Orbita bez zmian.
  - Dane: `lunar_pds_data/` i `MODI_PDS_DATA_DIR`.
  - `/health` zwraca `features: 10`. Wymagania przeglądarki: WebGL2 i `MAX_TEXTURE_SIZE ≥ 8192`.
- [ ] **Step 2: Limit pamięci.**
  - Lokalnie `docker compose -f docker-compose.prod.yml up -d --build`.
  - Zmierz szczyt (`docker stats lunarsims`) podczas budowy map zasobów i 5 obserwatorów, w tym bieguna.
  - Ustaw `mem_limit = max(2g, 1.5 × szczyt zaokrąglone w górę do 0.5g)` i zaktualizuj komentarz: newlunar 4.3 GB → geografia plus radius.
- [ ] **Step 3:** Przejdź sekcję „Weryfikacja end-to-end” poniżej.
- [ ] **Step 4:** Commit `docs: Powierzchnia GPU (WebGL2) i Zasoby; mem_limit po zmierzeniu`.

## Weryfikacja end-to-end

```bash
docker compose up --build                       # dev, http://localhost:8000
API=http://localhost:8000/api/v1
curl -s localhost:8000/health                   # {"status":"ok","features":10}
curl -s $API/lunar_surface/catalog | python3 -m json.tool | head -30
curl -s "$API/lunar_surface/observer?lat_deg=-89.48&lon_deg=129.8" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['r_max_km'],d['slope_deg'],len(d['horizon']['alt_deg']))"
curl -s $API/lunar_surface/tiles/dem/15/7 | wc -c                     # 129600
curl -s "$API/lunar_resources/roi?lat_deg=20&lon_deg=-25&radius_km=250" | python3 -m json.tool | head -20
git diff --stat main -- geografia.py radius.py generator.py neworb.py newlunar.py actualgpu.py gpu.py   # pusto
```

W przeglądarce (`/sim.html`):
- `#surface`: Tycho, presety 1–5, E/S/L, M, H, C i odtwarzanie (Space). HUD jest zgodny z `geografia.py`. W DevTools → Network serwer dostaje tylko `observer`, `sky` (≤5/s przy odtwarzaniu) i kafle; po zmianie lokacji kafle wracają z cache.
- `#resources`: zgodność z `radius.py`.
- `#orbit` bez regresji.

Obciążenie: w `top` na serwerze proces uvicorn jest bezczynny podczas obracania kamerą i zoomu na Powierzchni. Całą pracę per klatka robi GPU i przeglądarka klienta.
