"""Import root-skryptów repo (``newlunar.py``, ``neworb.py``) jako bibliotek obliczeniowych.

Skrypty są aplikacjami pygame i robią ``import pygame`` na poziomie modułu
(``newlunar.py:8``, ``neworb.py:27``), choć funkcje, których używa backend, są czystym
numpy/numba. W obrazie Dockera pygame nie ma, więc wtedy podstawiamy pusty moduł
``pygame`` (ten sam wzorzec co ``dte_line_of_sight.py:291-304``). Skryptów nie
modyfikujemy — wyłącznie je importujemy.
"""

import importlib
import os
import sys
import types
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def import_root_script(name: str, scripts_dir: Path) -> types.ModuleType:
    """Importuje ``<scripts_dir>/<name>.py``; brak pygame → atrapa pustego modułu."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        import pygame  # noqa: F401
    except ImportError:
        sys.modules["pygame"] = types.ModuleType("pygame")
    path = str(Path(scripts_dir).resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(name)
