# lunarsims.reachit.space — produkcyjny kontener (modi2026) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produkcyjny `docker-compose.prod.yml`, który uruchamia aplikację MODI 2026 (FastAPI + front Three.js w jednym procesie) na mainserv (192.168.0.3) pod `127.0.0.1:4550`, zgodnie z planem edge dla `lunarsims.reachit.space` z repo bieldent.

**Architecture:** Ruch: edge-nginx na NAS (TLS, lineage `lunarsims`) → `upstream lan_web` (SNI `lan-backend.internal`) → nginx na .3 (vhost `lunarsims.reachit.space`, `proxy_pass http://127.0.0.1:4550`) → ten kontener (`uvicorn :8000`). Nginx i certyfikat robi osobny plan w bieldent (`35-lunarsims.conf`, `lan-backend/lunarsims.conf`). Ten plan dostarcza tylko kontener i jego instrukcję. Obraz budujemy z istniejącego `Dockerfile`, a `Textures/` i `coords/` montujemy read-only z checkoutu (są w git, `.dockerignore` je wycina z obrazu).

**Tech Stack:** Docker Compose v2, istniejący `Dockerfile` (python:3.12-slim, uvicorn 0.34, FastAPI 0.115).

**Spec:** prośba użytkownika w tej sesji + plan edge z innej sesji (wklejony w odpowiedzi): port `4550`, kontener tylko na `127.0.0.1`, front + API w jednym procesie, bez WebSocketów, body ≤ 4M, nic wspólnego z kliniką.

## Context

Projekt ma stać na subdomenie `lunarsims.reachit.space` z certyfikatem SSL, „po prostu serwowany na kontener przez LAN”, bez integracji z resztą. Wzorzec to `wiseorganise.reachit.space` (bieldent `9b6ddf4`, `server/mainserv/nginx/conf.d/34-wiseorganise.conf`, DEPLOY.md „Nowa domena na .3 (nginx)”). Obecny `docker-compose.yml` jest deweloperski: montuje kod, używa `--reload` i publikuje `8000` na wszystkich interfejsach. Na serwer potrzebny jest osobny plik produkcyjny.

## Global Constraints

- Port: `127.0.0.1:4550:8000`. Tylko loopback, bo Docker omija ufw, a na LAN ma być wystawione wyłącznie 443 nginxa na .3.
- Kontener słucha na `8000` (z `Dockerfile`, `HEALTHCHECK` na `/health`).
- Brak montowania kodu i brak `--reload` w produkcji.
- Projekt compose `name: lunarsims`, kontener `lunarsims`, więc nie koliduje z deweloperskim `modi2026` (8000).
- Brak testów automatycznych w modi2026: weryfikacja tylko uruchomieniem (curl/logi/przeglądarka).
- Commit na gałęzi `feat/prod-compose-lunarsims` (nie na `main`), trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Port na `0.0.0.0` zamiast `127.0.0.1`.** Aplikacja byłaby wtedy na całym LAN-ie z ominięciem ufw. Oczekiwane: `ss -ltn` pokazuje tylko `127.0.0.1:4550` (Task 1, krok 3).
2. **Pliki z checkoutu nieczytelne dla uid 65534.** Tekstury wracają wtedy 401/500, a w przeglądarce jest czarna kula. Oczekiwane: każdy `/textures/*` z kontraktów → 200 (Task 1, krok 3).
3. **Read-only rootfs.** Jeśli coś zapisuje przy starcie, kontener wpada w pętlę restartów. Oczekiwane: status `healthy`, a `/health` zwraca `{"status":"ok","features":7}` (Task 1, krok 3).
4. **Limit edge kopiowany z wiseorganise (60r/m, burst 30).** `FrameScheduler` wysyła do ~4 zapytań/s `/api/v1/frame` przy odtwarzaniu (`docs/ARCHITECTURE.md:78-80`), a pierwsze ładowanie to ~30 plików (21 modułów JS, CSS, tekstury, manifest). Przy tym limicie odtwarzanie dostaje 429. Oczekiwane: brak 429 przy Play. To trzeba poprawić w planie bieldent, sprawdzamy w Task 2, krok 4.
5. **IP klienta za dwoma proxy.** Bez `--forwarded-allow-ips` uvicorn loguje bramę dockera (172.x). Oczekiwane: w `docker logs` widać IP z `X-Forwarded-For` (Task 1, krok 3).

## Uwagi do planu bieldent (do przekazania tamtej sesji)

- **`lunar_general`:** zamiast wartości z wiseorganise ustawić `rate=10r/s` i `burst=60 nodelay`, z nowymi nazwami stref, jak w tamtym planie. Uzasadnienie w Review Focus #4.
- **`lan-backend/lunarsims.compose.yaml`:** usunąć z tamtego planu. Jedynym źródłem jest `docker-compose.prod.yml` w modi2026. Tamten szkic montuje `./data/textures` i `./data/coords`, a takich katalogów w modi2026 nie ma: dane leżą w `./Textures` i `./coords`. Paragraf w README bieldent może po prostu wskazać ten plik.
- **Vhost na .3:** `Host`, `X-Forwarded-Proto https` i `X-Forwarded-For` z tamtego planu są zgodne z tym kontenerem, bez zmian.

---

### Task 1: `docker-compose.prod.yml` + sekcja „Produkcja” w dokumentacji

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `docs/superpowers/plans/2026-11-14-lunarsims-prod-compose.md` (kopia tego planu)
- Modify: `docs/ARCHITECTURE.md` (nowa sekcja `## Produkcja` po `## Uruchamianie`, przed `## Jak sprawdzić, czy działa`)

**Interfaces:**
- Consumes: `Dockerfile` (bez zmian): obraz z `/srv/backend`, `/srv/contracts`, `/srv/frontend`, env `MODI_TEXTURES_DIR=/data/textures`, `MODI_COORDS_DIR=/data/coords`, `HEALTHCHECK` na `127.0.0.1:8000/health`.
- Produces (dla nginx na .3): HTTP na `127.0.0.1:4550`. Akceptuje `Host: lunarsims.reachit.space`, honoruje `X-Forwarded-For` i `X-Forwarded-Proto`.

- [ ] **Step 1: Gałąź i kopia planu**

`git switch -c feat/prod-compose-lunarsims`, potem skopiuj ten plan do `docs/superpowers/plans/2026-11-14-lunarsims-prod-compose.md`.

- [ ] **Step 2: Utwórz `docker-compose.prod.yml`**

Każda linia to decyzja, więc plik w całości:

```yaml
# Produkcja: lunarsims.reachit.space na mainserv (192.168.0.3).
# edge (NAS, TLS) -> nginx na .3 (vhost po Host) -> 127.0.0.1:4550 -> ten kontener.
# Start/aktualizacja: git pull && docker compose -f docker-compose.prod.yml up -d --build
name: lunarsims

services:
  lunarsims:
    build: .
    image: lunarsims:prod
    container_name: lunarsims
    restart: unless-stopped
    # Tylko loopback: Docker omija ufw, a na LAN wystawione jest wyłącznie 443 nginxa na .3.
    ports:
      - "127.0.0.1:4550:8000"
    volumes:
      - ./Textures:/data/textures:ro
      - ./coords:/data/coords:ro
    # Bez --reload. '*' jest bezpieczne, bo port słucha tylko na loopbacku: nagłówki
    # X-Forwarded-* może ustawić wyłącznie nginx z .3. Ruch przychodzi z bramy dockera (172.x),
    # więc domyślne 127.0.0.1 by je ignorowało.
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
              "--proxy-headers", "--forwarded-allow-ips", "*"]
    # Side project na wspólnym serwerze: bez roota, bez zapisu, bez capabilities.
    user: "65534:65534"
    read_only: true
    tmpfs:
      - /tmp
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    mem_limit: 1g
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

Sprawdzenie: `docker compose -f docker-compose.prod.yml config -q` → brak wyjścia, kod 0.

- [ ] **Step 3: Smoke test lokalnie (pokrywa Review Focus 1, 2, 3, 5)**

```bash
docker compose -f docker-compose.prod.yml up -d --build
until [ "$(docker inspect -f '{{.State.Health.Status}}' lunarsims)" != starting ]; do sleep 2; done
docker inspect -f '{{.State.Health.Status}} {{.HostConfig.RestartPolicy.Name}}' lunarsims   # healthy unless-stopped
ss -ltn | grep ':4550 '                                                                     # tylko 127.0.0.1:4550
curl -s 127.0.0.1:4550/health                                                               # {"status":"ok","features":7}
curl -s "127.0.0.1:4550/api/v1/frame?t=2026-01-01T00:00:00Z&lat_deg=10" | python3 -c 'import sys,json; print(json.load(sys.stdin)["errors"])'   # {}
grep -ho '"/textures/[^"]*"' contracts/examples/*.json | sort -u | tr -d '"' \
  | while read u; do echo "$(curl -sI -o /dev/null -w '%{http_code}' 127.0.0.1:4550$u) $u"; done          # same 200
curl -s -o /dev/null -H 'Host: lunarsims.reachit.space' -H 'X-Forwarded-For: 203.0.113.7' 127.0.0.1:4550/
docker logs --tail 1 lunarsims                                                              # zawiera 203.0.113.7
```

W przeglądarce `http://127.0.0.1:4550`: panel warstw ma 7 pozycji, a tekstury Ziemi i Księżyca są widoczne. Na koniec: `docker compose -f docker-compose.prod.yml down`.

- [ ] **Step 4: Sekcja `## Produkcja` w `docs/ARCHITECTURE.md`**

Po polsku, ok. 15 linii, zawiera:
- adres `https://lunarsims.reachit.space` i drogę ruchu (jedna linia jak w „Architecture” wyżej);
- port `127.0.0.1:4550` i zakaz zmiany bez zmiany vhosta na .3;
- że nginx (edge `35-lunarsims.conf`, .3 `lan-backend/lunarsims.conf`) i certyfikat (lineage `lunarsims`) są w repo bieldent `server/mainserv/`, a nie tutaj;
- komendy: start i aktualizacja (`git pull && docker compose -f docker-compose.prod.yml up -d --build`), logi (`docker logs -f lunarsims`), zdrowie (`curl -s 127.0.0.1:4550/health`);
- że `Textures/` i `coords/` z checkoutu muszą być czytelne dla „others” (`o+r`), bo kontener działa jako uid 65534.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.prod.yml docs/ARCHITECTURE.md docs/superpowers/plans/2026-11-14-lunarsims-prod-compose.md
git commit -m "feat(deploy): production compose for lunarsims.reachit.space on 127.0.0.1:4550"
```

### Task 2: Wdrożenie na mainserv (ręcznie: wykonujesz ty, ja podaję komendy)

Kolejność względem planu bieldent: ten task to jego krok **3b**. Robi się go po DNS (3a), a przed vhostem na .3 (3c) i `setup.sh` na NAS (3d).

- [ ] **Step 1:** Na .3: `ss -ltn | grep ':4550 '`. Oczekiwane: pusto (port wolny).
- [ ] **Step 2:** Na .3: `git clone <repo modi2026> /srv/lunarsims && cd /srv/lunarsims && git switch feat/prod-compose-lunarsims` (albo `main` po merge'u). Następnie `docker compose -f docker-compose.prod.yml up -d --build`.
- [ ] **Step 3:** Na .3: `curl -s 127.0.0.1:4550/health` → `{"status":"ok","features":7}`, a `docker inspect -f '{{.State.Health.Status}}' lunarsims` → `healthy`.
- [ ] **Step 4:** Po krokach 3c–3e planu bieldent, z sieci spoza LAN: `curl -sI https://lunarsims.reachit.space/` → `200`, cert Let's Encrypt, a nie placeholder `CN=lunarsims`. W przeglądarce kliknij Play przy prędkości „1 dzień/s” na 30 s. W DevTools/Network żadne `/api/v1/frame` nie może mieć statusu 429 (Review Focus #4).

## Self-Review

- Pokrycie: kontener produkcyjny (T1), zgodność z portem i nagłówkami nginx (T1, Interfaces), wdrożenie (T2), SSL i nginx (plan bieldent; uwagi wyżej).
- Spójność: `4550`, `lunarsims`, `/data/textures`, `/data/coords` są te same w compose, dokumentacji i planie bieldent.
- Poza zakresem: skrypty pygame (`orbital.py`, `lunar_stellarium.py`), czyli aplikacje desktopowe, oraz zmiany w `Dockerfile` i deweloperskim `docker-compose.yml`.

## Wykonanie

Polecam **Native** (superpowers:executing-plans): jeden task z kodem, jeden plik konfiguracyjny i smoke test. Osobny subagent na task tylko by tu kosztował.
