from __future__ import annotations

from typing import Iterable

from bs4 import BeautifulSoup

from .. import http
from ..models import Filters, Listing, slug, to_int
from .base import Source

BASE = "https://www.argenprop.com"
TIPOS = {"departamento": "departamentos", "casa": "casas", "ph": "ph"}
OPERACIONES = {"venta": "venta", "alquiler": "alquiler"}
MONEDAS = {"USD": "dolares", "ARS": "pesos"}


class Argenprop(Source):
    name = "argenprop"
    label = "Argenprop"

    # Argenprop corta con un desafío anti-bot si recibe pedidos seguidos: se va despacio y con pocas fichas
    detail_budget = 8
    check_barrio = False  # la tarjeta a veces solo trae el sub-barrio ("Barrio Chino")
    max_pages = 5

    def _url(self, f: Filters, ambientes: int | None) -> str:
        parts = [TIPOS.get(f.tipo, "departamentos"), OPERACIONES.get(f.operacion, "venta")]
        if f.barrios:
            # Belgrano incluye sus sub-barrios; Belgrano R además existe como zona propia
            zonas = ("belgrano" if "belgrano" in slug(b) and slug(b) != "belgrano-r" else slug(b) for b in f.barrios)
            parts.append("-o-".join(dict.fromkeys(zonas)))
        if ambientes:
            parts.append(f"{ambientes}-ambientes")
        if f.precio_max:
            parts.append(f"{MONEDAS.get(f.moneda, 'dolares')}-hasta-{f.precio_max}")
        return f"{BASE}/" + "/".join(parts)

    def search(self, f: Filters) -> Iterable[Listing]:
        http.HOST_DELAY["www.argenprop.com"] = 10
        for ambientes in f.ambientes(extra=1):
            yield from self._search(self._url(f, ambientes))

    def _search(self, url: str) -> Iterable[Listing]:
        for page in range(1, self.max_pages + 1):
            soup = BeautifulSoup(http.get(url + (f"?pagina-{page}" if page > 1 else "")).text, "html.parser")
            cards = soup.select("div.listing__item a.card[data-item-card]")
            for a in cards:
                feats = {}
                for li in a.select(".card__main-features li"):
                    icon = li.find("i")
                    feats[(icon.get("class") or [""])[0].rsplit("-", 1)[-1] if icon else ""] = li.get_text(" ", strip=True)
                price_el = a.select_one(".card__price")
                currency_el = a.select_one(".card__currency")
                img = a.select_one(".card__photos img")
                address = a.select_one(".card__address")
                expenses = a.select_one(".card__expenses")
                yield Listing(
                    source=self.name,
                    id=a["data-item-card"],
                    url=BASE + a["href"],
                    title=(a.select_one(".card__title") or a).get_text(" ", strip=True)[:200],
                    price=to_int(a.get("montooperacion")) or (to_int(price_el.get_text()) if price_el else None),
                    currency={"USD": "USD", "$": "ARS"}.get(currency_el.get_text(strip=True), None) if currency_el else None,
                    expenses=expenses.get_text(" ", strip=True) if expenses else None,
                    address=address.get_text(" ", strip=True) if address else "",
                    location=address.get_text(" ", strip=True) if address else "",
                    rooms=to_int(feats.get("cantidad_ambientes")),
                    bedrooms=to_int(feats.get("cantidad_dormitorios")) or to_int(a.get("dormitorios")),
                    bathrooms=to_int(feats.get("cantidad_banos")),
                    area=to_int(feats.get("superficie_cubierta") or feats.get("superficie_total")),
                    description=(a.select_one(".card__info") or a).get_text(" ", strip=True)[:1500],
                    image=(img.get("src") or img.get("data-src")) if img else None,
                )
            if not soup.select_one(".pagination__page-next [data-link-href]"):
                break
