from __future__ import annotations

import json
import unicodedata
from typing import Iterable

from bs4 import BeautifulSoup

from .. import http
from ..models import Filters, Listing, norm
from .base import Source

BASE = "https://lepore.com.ar"
SEARCH = BASE + "/propiedades"
# ids del formulario de búsqueda del sitio
OPERACIONES = {"venta": 1, "alquiler": 2, "temporario": 3}
TIPOS = {"departamento": 2, "casa": 1, "ph": 14}
MONEDAS = {"USD": 1, "ARS": 2}


def _ascii(text: str) -> str:
    """El sitio rompe la ñ al redirigir ('Nuñez' queda sin resultados); sin acento sí la reconoce."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


class Lepore(Source):
    name = "lepore"
    label = "Lepore"

    def _params(self, f: Filters) -> dict:
        params: dict = {"operation[]": OPERACIONES.get(f.operacion, 1), "type[]": TIPOS.get(f.tipo, 2), "order": 1}
        if f.precio_max:
            params.update(currency=MONEDAS.get(f.moneda, 1), price_to=f.precio_max)
        if f.ambientes_min and f.ambientes_min > 2:
            # solo filtra por dormitorios (el 4 es "4 o más"); se deja un ambiente de margen
            low = min(f.ambientes_min - 2, 4)
            params["bedroom_ranges[]"] = list(range(low, min(max((f.ambientes_max or 9) - 1, low), 4) + 1))
        return params

    def _zonas(self, f: Filters, params: dict) -> list[str]:
        """Valores de zona del formulario. Solo se listan cuando todavía no hay ninguna elegida.

        Cada barrio incluye sus subzonas (Belgrano -> Belgrano C); uno sin zona propia (Belgrano R) cae en la del barrio base.
        """
        soup = BeautifulSoup(http.get(SEARCH, params=params).text, "html.parser")
        todas = {norm(v.rsplit(",", 1)[-1].replace("+", " ")): _ascii(v) for v in (i.get("value") or "" for i in soup.select('#search-form input[name="location[]"]')) if v}
        zonas: list[str] = []
        for b in f.barrios:
            w = norm(b)
            hits = [v for label, v in todas.items() if label == w or label.startswith(w + " ")]
            hits = hits or [v for label, v in todas.items() if w.startswith(label + " ")]
            zonas += [v for v in hits if v not in zonas]
        return zonas

    def search(self, f: Filters) -> Iterable[Listing]:
        params = self._params(f)
        if f.barrios:
            params["location[]"] = self._zonas(f, params)
            if not params["location[]"]:
                return  # el sitio no tiene avisos de ese tipo en esos barrios
        seen: set[str] = set()
        # primero los que el sitio marca "con cochera": la tarjeta no lo dice, el filtro sí
        for garage in (True, None):
            yield from self._search({**params, "with_garage": 1} if garage else params, garage, seen)

    def _search(self, params: dict, garage: bool | None, seen: set[str]) -> Iterable[Listing]:
        url = SEARCH
        for page in range(1, self.max_pages + 1):
            resp = http.get(url, params=params if page == 1 else {"page": page})
            if page == 1:
                url = resp.url  # el formulario redirige a una URL "linda"; se pagina sobre esa
            soup = BeautifulSoup(resp.text, "html.parser")
            for card in soup.select(".property-item[data-id]"):
                ld = card.find("script", type="application/ld+json")
                if card["data-id"] in seen or not ld:
                    continue
                seen.add(card["data-id"])
                data = json.loads(ld.string or "{}")
                about, offer = data.get("about") or {}, data.get("offers") or {}
                addr = about.get("address") or {}
                expenses, desc = card.select_one(".expenses"), card.select_one(".description")
                area = (about.get("floorSize") or {}).get("value")
                yield Listing(
                    source=self.name,
                    id=card["data-id"],
                    url=data.get("url") or BASE + card.select_one("a[href]")["href"],
                    title=" ".join((data.get("name") or "").split()),
                    price=int(offer["price"]) if offer.get("price") else None,
                    currency=offer.get("priceCurrency") if offer.get("price") else None,
                    expenses=expenses.get_text(" ", strip=True).replace("Expensas:", "").strip() or None if expenses else None,
                    address=" ".join((addr.get("streetAddress") or "").split()).title(),
                    location=", ".join(p for p in (addr.get("addressLocality"), addr.get("addressRegion")) if p),
                    rooms=about.get("numberOfRooms") or None,
                    bedrooms=about.get("numberOfBedrooms") or None,
                    bathrooms=about.get("numberOfBathroomsTotal") or None,
                    area=int(area) if area else None,  # superficie total
                    garage=garage,
                    description=" ".join(desc.get_text(" ", strip=True).split()) if desc else "",
                    image=data.get("image"),
                )
            if not any(f"page={page + 1}" in (a.get("href") or "") for a in soup.select(".pagination a")):
                break

    def detail_text(self, listing: Listing) -> str:
        # se corta antes de "Propiedades Similares": son otros avisos y confundirían cochera/balcón
        return http.html_to_text(http.get(listing.url).text).split("Propiedades Similares")[0]
