"""Uruchamia strony ``/sim.html`` oraz ``/dwa wykresy.html`` (backend FastAPI) bez Dockera — Windows, Linux, macOS.

    py -3.12 run_local.py              # Windows
    python3.12 run_local.py            # Linux / macOS
    py -3.12 run_local.py --port 8001  # gdy port 8000 jest zajęty
"""

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
FRONTEND_DIR = REPO / "frontend"
BACKEND_DIR = REPO / "backend"
VENV = REPO / ".venv"
REQUIREMENTS = BACKEND_DIR / "requirements.txt"
PY_VERSION = (3, 12)

REQUIRED_DATA = (
    "Textures/moon_dem_nasa_16ppd_v3.npy",
    "Textures/moon_color_nasa_8k_v3.npy",
    "coords/2026.csv",
    "frontend/linear_interpolation_position.py",
    "frontend/time_zone_converter.py",
    "frontend/energy_plot_generator.py",
    "frontend/elevation_plot_generator.py",
)
STAMP = VENV / "requirements.sha256"


def fail(message: str) -> None:
    print(f"[BŁĄD] {message}", file=sys.stderr)
    sys.exit(1)


def check_python() -> None:
    if sys.version_info[:2] != PY_VERSION:
        fail(
            f"Potrzebny jest Python 3.12 (jak w Dockerze), a uruchomiono {sys.version.split()[0]}.\n"
            "  Instalacja na Windows:  winget install -e --id Python.Python.3.12\n"
            "                          (albo instalator 3.12 z https://www.python.org/downloads/)\n"
            "  Potem uruchom:          py -3.12 run_local.py"
        )


def check_data() -> None:
    missing = [p for p in REQUIRED_DATA if not (REPO / p).is_file()]
    if missing:
        fail(
            "Brak plików danych:\n"
            + "".join(f"  - {p}\n" for p in missing)
            + "  Sklonuj repo ponownie (git clone), nie pobieraj pojedynczych plików."
        )


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _venv_version() -> str:
    cfg = VENV / "pyvenv.cfg"
    if not cfg.is_file():
        return ""
    for line in cfg.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("version", "version_info"):
            return value.strip()
    return ""


def ensure_venv() -> Path:
    if not VENV.exists():
        print(f"Tworzę środowisko {VENV} …")
        if subprocess.call([sys.executable, "-m", "venv", str(VENV)]) != 0:
            fail("Nie udało się utworzyć .venv.")
    elif not _venv_version().startswith("3.12"):
        fail(
            f"Folder .venv jest z innego Pythona ({_venv_version() or 'nieznana wersja'}).\n"
            "  Usuń go i uruchom ponownie:  Remove-Item -Recurse -Force .venv   (PowerShell)\n"
            "                               rm -rf .venv                         (Linux / macOS)"
        )

    vpy = venv_python()
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not STAMP.is_file() or STAMP.read_text(encoding="utf-8").strip() != digest:
        print("Instaluję zależności z backend/requirements.txt (pierwszy raz kilka minut) …")
        cmd = [str(vpy), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)]
        if subprocess.call(cmd) != 0:
            fail("pip install nie powiódł się — sprawdź połączenie z internetem i komunikat powyżej.")
        STAMP.write_text(digest, encoding="utf-8")
    return vpy


def create_app():
    """Fabryka aplikacji FastAPI uruchamiana przez uvicorn wewnątrz .venv."""
    import traceback
    from datetime import datetime

    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel

    for p in (str(REPO), str(BACKEND_DIR), str(FRONTEND_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)

    import elevation_plot_generator as elev_gen
    import energy_plot_generator as energy_gen
    import time_zone_converter as tz_conv
    from app.main import app

    router = APIRouter()

    class WykresyRequest(BaseModel):
        liczba_wykresow: int = 2
        lat1: float
        lon1: float
        lat2: float
        lon2: float
        metric: str
        data_poczatek: str
        data_koniec: str
        utc_offset: str | None = None
        kraj: str | None = None
        region: str | None = None

    def _wyznacz_strefe_iana(utc_offset: str | None, kraj: str | None, region: str | None) -> str:
        if utc_offset:
            return utc_offset.strip()
        if not kraj:
            raise ValueError("Nie podano strefy czasowej (ani przesunięcia UTC, ani kraju).")
        strefa = tz_conv.define_IANA_zone(kraj, region)
        if strefa.startswith("Błąd"):
            raise ValueError(f"{strefa} dla kraju '{kraj}'.")
        return strefa

    def _oblicz_dla_lokalizacji(
        lat_deg: float,
        lon_deg: float,
        metric: str,
        data_poczatek: str,
        data_koniec: str,
        utc_offset: str | None,
        kraj: str | None,
        region: str | None,
    ) -> dict:
        strefa_iana = _wyznacz_strefe_iana(utc_offset, kraj, region)
        tymczasowy_klucz = "__CUSTOM_UTC_ZONE__"
        uzyto_tymczasowego = False

        if utc_offset:
            tz_conv.kraje_i_strefy_iana[tymczasowy_klucz] = strefa_iana
            kraj_do_wywolania = tymczasowy_klucz
            region_do_wywolania = None
            uzyto_tymczasowego = True
        else:
            kraj_do_wywolania = kraj
            region_do_wywolania = region

        try:
            if metric in ("earth_alt", "sun_alt"):
                tablica, wysokosci_gor_ziemia = elev_gen._oblicz_dane_elewacji(
                    data_poczatek_lokalna=data_poczatek,
                    data_koniec_lokalna=data_koniec,
                    kraj=kraj_do_wywolania,
                    region=region_do_wywolania,
                    lat_deg=lat_deg,
                    lon_deg=lon_deg,
                )
                daty_str = [w[0] for w in tablica]
                daty_dt = [datetime.strptime(d, "%Y-%m-%d %H:%M") for d in daty_str]
                strefa_utc = elev_gen._formatuj_strefe_utc(strefa_iana, daty_dt)

                if metric == "earth_alt":
                    return {
                        "lat": lat_deg,
                        "lon": lon_deg,
                        "strefa_utc": strefa_utc,
                        "daty": daty_str,
                        "elewacja_ziemi_deg": [w[2] for w in tablica],
                        "wysokosc_gor_deg": wysokosci_gor_ziemia,
                    }
                return {
                    "lat": lat_deg,
                    "lon": lon_deg,
                    "strefa_utc": strefa_utc,
                    "daty": daty_str,
                    "elewacja_slonca_deg": [w[1] for w in tablica],
                    "wysokosc_gor_deg": [w[3] for w in tablica],
                }

            if metric in ("panel_parallel", "panel_perpendicular", "panel_tracking"):
                tabela, _ = energy_gen.generuj_dane_naslonecznienia(
                    data_poczatek_lokalna=data_poczatek,
                    data_koniec_lokalna=data_koniec,
                    kraj=kraj_do_wywolania,
                    region=region_do_wywolania,
                    lat_deg=lat_deg,
                    lon_deg=lon_deg,
                )
                daty_str = [w[0] for w in tabela]
                daty_dt = [datetime.strptime(d, "%Y-%m-%d %H:%M") for d in daty_str]
                strefa_utc = energy_gen._formatuj_strefe_utc(strefa_iana, daty_dt)

                if metric == "panel_parallel":
                    kol_nat, kol_eng = 1, 2
                elif metric == "panel_perpendicular":
                    kol_nat, kol_eng = 3, 4
                else:
                    kol_nat, kol_eng = 5, 6

                return {
                    "lat": lat_deg,
                    "lon": lon_deg,
                    "strefa_utc": strefa_utc,
                    "daty": daty_str,
                    "natezenie_w_m2": [w[kol_nat] for w in tabela],
                    "energia_skumulowana_j_m2": [w[kol_eng] for w in tabela],
                }

            raise ValueError(f"Nieznany typ wykresu: {metric}")
        finally:
            if uzyto_tymczasowego:
                tz_conv.kraje_i_strefy_iana.pop(tymczasowy_klucz, None)

    @router.get("/api/strefy")
    def pobierz_strefy():
        return {
            "kraje": tz_conv.kraje_i_strefy_iana,
            "regiony": tz_conv.regiony_i_strefy_iana,
        }

    @router.post("/api/wykresy")
    def oblicz_wykresy(dane: WykresyRequest):
        try:
            miejsce1 = _oblicz_dla_lokalizacji(
                dane.lat1,
                dane.lon1,
                dane.metric,
                dane.data_poczatek,
                dane.data_koniec,
                dane.utc_offset,
                dane.kraj,
                dane.region,
            )
            miejsce2 = None
            if dane.liczba_wykresow == 2:
                miejsce2 = _oblicz_dla_lokalizacji(
                    dane.lat2,
                    dane.lon2,
                    dane.metric,
                    dane.data_poczatek,
                    dane.data_koniec,
                    dane.utc_offset,
                    dane.kraj,
                    dane.region,
                )
            return {"miejsce1": miejsce1, "miejsce2": miejsce2}
        except Exception as exc:
            traceback.print_exc()
            return JSONResponse(status_code=400, content={"error": str(exc)})

    # Wstaw trasy API przed montowaniem StaticFiles("/")
    mount_idx = next(
        (i for i, r in enumerate(app.router.routes) if getattr(r, "path", None) in ("", "/")),
        len(app.router.routes),
    )
    for route in reversed(router.routes):
        app.router.routes.insert(mount_idx, route)

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Uruchamia /sim.html oraz /dwa wykresy.html bez Dockera (Python 3.12).")
    parser.add_argument("--port", type=int, default=8000, help="port serwera (domyślnie 8000)")
    args = parser.parse_args(argv)

    check_python()
    check_data()
    vpy = ensure_venv()

    print(f"\nSymulacja: http://127.0.0.1:{args.port}/sim.html", flush=True)
    print(f"Wykresy:   http://127.0.0.1:{args.port}/dwa%20wykresy.html   (Ctrl+C kończy)\n", flush=True)

    pythonpath = os.pathsep.join(
        filter(None, [str(REPO), str(BACKEND_DIR), str(FRONTEND_DIR), os.environ.get("PYTHONPATH", "")])
    )
    env = os.environ | {
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": pythonpath,
    }
    cmd = [
        str(vpy),
        "-m",
        "uvicorn",
        "run_local:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
    ]
    try:
        return subprocess.call(cmd, cwd=BACKEND_DIR, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())