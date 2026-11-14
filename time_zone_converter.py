from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def convert_time_zone(data_utc_str: str, strefa_docelowa: str) -> str:
    """
    Konwertuje czas z formatu 'yyyy-mm-dd hh:mm' (UTC) na podaną strefę czasową
    z automatycznym uwzględnieniem czasu zimowego i letniego (DST).

    :param data_utc_str: Data w formacie 'YYYY-MM-DD HH:MM' (w UTC)
    :param strefa_docelowa: Nazwa strefy z bazy IANA, np. 'Europe/Warsaw', 'America/New_York'
    :return: Przekonwertowana data w formacie 'YYYY-MM-DD HH:MM'
    """
    # 1. Parsowanie stringa do obiektu datetime i przypisanie mu strefy UTC
    dt_utc = datetime.strptime(data_utc_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)

    # 2. Konwersja na docelową strefę czasową (automatyczne uwzględnienie czasu letniego/zimowego)
    dt_lokalny = dt_utc.astimezone(ZoneInfo(strefa_docelowa))

    # 3. Zwrócenie samej daty i godziny
    return dt_lokalny.strftime("%Y-%m-%d %H:%M")


