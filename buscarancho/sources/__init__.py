from __future__ import annotations

import importlib
import pkgutil

from .base import Source


def all_sources() -> dict[str, Source]:
    """Descubre todas las subclases de Source definidas en esta carpeta."""
    for mod in pkgutil.iter_modules(__path__):
        if mod.name != "base":
            importlib.import_module(f"{__name__}.{mod.name}")
    return {cls.name: cls() for cls in Source.__subclasses__() if cls.name}
