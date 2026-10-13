from __future__ import annotations

from typing import Iterable

from .. import http
from ..models import Filters, Listing


class Source:
    """Un portal de propiedades.

    Para agregar uno nuevo: crear un archivo en esta carpeta con una subclase que
    defina `name`, `label` y `search()`. Se registra solo (ver sources/__init__.py).

    `search()` usa los filtros para acotar la búsqueda lo mejor que el portal permita;
    no hace falta que sea exacto: el filtrado final lo aplica matching.py igual para todos.
    """

    name: str = ""
    label: str = ""
    max_pages: int = 8
    detail_budget: int = 40  # fichas individuales que se abren por corrida
    check_barrio: bool = True  # False si el portal ya filtra bien por barrio y no lo repite en la ubicación

    def search(self, f: Filters) -> Iterable[Listing]:
        raise NotImplementedError

    def detail_text(self, listing: Listing) -> str:
        """Texto de la ficha del aviso, para confirmar cochera/balcón/baños cuando la tarjeta no lo dice."""
        return http.html_to_text(http.get(listing.url).text)
