#!/usr/bin/env python3
"""Uruchamia stronę ``/sim.html`` (backend FastAPI) bez Dockera — Windows, Linux, macOS.

    py -3.12 run_local.py              # Windows
    python3.12 run_local.py            # Linux / macOS
    py -3.12 run_local.py --port 8001  # gdy port 8000 jest zajęty

Skrypt odtwarza warunki z ``Dockerfile``, więc wyniki symulacji są takie same jak w kontenerze:

- Python 3.12 (obraz ``python:3.12-slim``); inna wersja → błąd zamiast instalacji;
- czysty ``.venv`` z ``backend/requirements.txt`` — te same przypięte wersje stosu numerycznego
  (numpy, numba → llvmlite, pandas), bez pygame, więc ``app/core/legacy.py`` podstawia tę samą
  atrapę modułu co w Dockerze;
- dane z repo (``Textures/`` z mapami v3, ``coords/``) — ścieżki domyślne z ``backend/app/settings.py``;
- ten sam proces: ``uvicorn app.main:app`` z katalogu ``backend/``, bez ``--reload``.
"""

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
VENV = REPO / ".venv"
REQUIREMENTS = REPO / "backend" / "requirements.txt"
PY_VERSION = (3, 12)
# Mapy terenu v3 (DEM_FILE / COLOR_FILE z backend/app/features/lunar_surface/facade.py) i efemerydy
REQUIRED_DATA = (
    "Textures/moon_dem_nasa_16ppd_v3.npy",
    "Textures/moon_color_nasa_8k_v3.npy",
    "coords/2026.csv",
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Uruchamia /sim.html bez Dockera (Python 3.12).")
    parser.add_argument("--port", type=int, default=8000, help="port serwera (domyślnie 8000)")
    args = parser.parse_args(argv)

    check_python()
    check_data()
    vpy = ensure_venv()

    print(f"\nSymulacja: http://127.0.0.1:{args.port}/sim.html   (Ctrl+C kończy)\n", flush=True)
    env = os.environ | {"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [str(vpy), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)]
    try:
        return subprocess.call(cmd, cwd=REPO / "backend", env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
