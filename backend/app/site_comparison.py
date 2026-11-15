"""Trasy strony porównania dwóch miejsc (``/dwa wykresy.html``): ``GET /api/strefy`` i ``POST /api/wykresy``.

Port 1:1 wpięcia z ``run_local.py`` z gałęzi ``feat/sim-page`` (autor strony): te same nazwy pól,
te same kolumny tabel i te same komunikaty. Obliczenia robią root-skrypty
``elevation_plot_generator.py`` / ``energy_plot_generator.py`` / ``time_zone_converter.py``,
importowane bez zmian przez ``import_root_script``.

Różnice wymuszone przez serwer (bez wpływu na wyniki):
- ``coords/`` i cache topografii LOLA idą jawnie ze ``Settings`` (argumenty ``folder``/
  ``folder_danych``/``folder_cache_topo`` skryptów), zamiast ``os.chdir`` i podmiany ``open``.
  W kontenerze rootfs jest read-only, więc cache ląduje w ``/tmp`` (``MODI_TOPO_CACHE_DIR``).
- Obliczenie jest pod blokadą: oryginał na chwilę dopisuje strefę ``__CUSTOM_UTC_ZONE__``
  do globalnego słownika ``time_zone_converter``, a FastAPI wykonuje trasy w wątkach.
"""

import threading
import traceback
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.legacy import import_root_script
from app.settings import Settings

__all__ = ["build_site_comparison_router"]


class WykresyRequest(BaseModel):
    liczba_wykresow: int = 2
    lat1: float
    lon1: float
    lat2: float
    lon2: float
    metric: str
    data_poczatek: str
    data_koniec: str
    utc_offset: Optional[str] = None
    kraj: Optional[str] = None
    region: Optional[str] = None


def build_site_comparison_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["site_comparison"])
    lock = threading.Lock()
    coords = str(settings.coords_dir)
    topo_cache = str(settings.topo_cache_dir)

    def scripts():
        tz_conv = import_root_script("time_zone_converter", settings.scripts_dir)
        elev_gen = import_root_script("elevation_plot_generator", settings.scripts_dir)
        energy_gen = import_root_script("energy_plot_generator", settings.scripts_dir)
        return tz_conv, elev_gen, energy_gen

    def dostepne_lata_csv() -> list:
        folder = settings.coords_dir
        if not folder.is_dir():
            return []
        return sorted(f.stem for f in folder.glob("*.csv") if f.stem.isdigit())

    def wyznacz_strefe_iana(tz_conv, utc_offset, kraj, region) -> str:
        if utc_offset:
            return utc_offset.strip()
        if not kraj:
            raise ValueError("Nie podano strefy czasowej (ani przesunięcia UTC, ani kraju).")
        strefa = tz_conv.define_IANA_zone(kraj, region)
        if strefa.startswith("Błąd"):
            raise ValueError(f"{strefa} dla kraju '{kraj}'.")
        return strefa

    def oblicz_dla_lokalizacji(lat_deg, lon_deg, metric, data_poczatek, data_koniec, utc_offset, kraj, region) -> dict:
        tz_conv, elev_gen, energy_gen = scripts()
        strefa_iana = wyznacz_strefe_iana(tz_conv, utc_offset, kraj, region)
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
                    folder=coords,
                    folder_cache_topo=topo_cache,
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
                    folder_danych=coords,
                    folder_cache_topo=topo_cache,
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

    @router.get("/api/strefy", summary="Kraje i regiony ze strefami IANA (time_zone_converter.py)")
    def pobierz_strefy():
        tz_conv, _, _ = scripts()
        return {
            "kraje": tz_conv.kraje_i_strefy_iana,
            "regiony": tz_conv.regiony_i_strefy_iana,
        }

    @router.post("/api/wykresy", summary="Wysokość Słońca/Ziemi lub nasłonecznienie paneli dla 1–2 miejsc")
    def oblicz_wykresy(dane: WykresyRequest):
        try:
            with lock:
                miejsce1 = oblicz_dla_lokalizacji(
                    dane.lat1, dane.lon1, dane.metric, dane.data_poczatek, dane.data_koniec,
                    dane.utc_offset, dane.kraj, dane.region,
                )
                miejsce2 = None
                if dane.liczba_wykresow == 2:
                    miejsce2 = oblicz_dla_lokalizacji(
                        dane.lat2, dane.lon2, dane.metric, dane.data_poczatek, dane.data_koniec,
                        dane.utc_offset, dane.kraj, dane.region,
                    )
            return {"miejsce1": miejsce1, "miejsce2": miejsce2}
        except Exception as exc:
            traceback.print_exc()
            lata = dostepne_lata_csv()
            msg = str(exc)
            if ("2025" in msg or "2027" in msg) and lata:
                msg = (
                    f"{msg} — Pamiętaj, że data lokalna jest przeliczana na UTC "
                    f"(np. 2026-01-01 00:00 w UTC+1 to 2025-12-31 23:00 UTC). "
                    f"Dostępne pliki w coords/: {', '.join(lata)}."
                )
            return JSONResponse(status_code=400, content={"error": msg})

    return router
