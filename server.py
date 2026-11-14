import json
import traceback
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import elevation_plot_generator as elev_gen

try:
    import energy_plot_generator as energy_gen
except ModuleNotFoundError:
    import energy_plot_generator_2 as energy_gen

import time_zone_converter as tz_conv


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


class LunarPlotHandler(SimpleHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            if Path("dwa wykresy.html").exists():
                self.path = "/dwa%20wykresy.html"
            elif Path("dwa wykresy_2.html").exists():
                self.path = "/dwa%20wykresy_2.html"
            return super().do_GET()

        if parsed.path == "/api/strefy":
            self._send_json(
                {
                    "kraje": tz_conv.kraje_i_strefy_iana,
                    "regiony": tz_conv.regiony_i_strefy_iana,
                }
            )
            return

        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/wykresy":
            self._send_json({"error": "Nieznany endpoint."}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length).decode("utf-8")
            dane = json.loads(body)

            lat1 = float(dane["lat1"])
            lon1 = float(dane["lon1"])
            lat2 = float(dane["lat2"])
            lon2 = float(dane["lon2"])
            metric = str(dane["metric"])
            data_poczatek = str(dane["data_poczatek"])
            data_koniec = str(dane["data_koniec"])
            utc_offset = dane.get("utc_offset")
            kraj = dane.get("kraj")
            region = dane.get("region")

            miejsce1 = _oblicz_dla_lokalizacji(
                lat1, lon1, metric, data_poczatek, data_koniec, utc_offset, kraj, region
            )
            miejsce2 = _oblicz_dla_lokalizacji(
                lat2, lon2, metric, data_poczatek, data_koniec, utc_offset, kraj, region
            )

            self._send_json({"miejsce1": miejsce1, "miejsce2": miejsce2})
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8000
    server = ThreadingHTTPServer((host, port), LunarPlotHandler)
    print(f"Serwer uruchomiony pod adresem: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nZatrzymywanie serwera...")
        server.server_close()
