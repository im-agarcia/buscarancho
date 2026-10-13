from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from .. import http
from ..models import Filters, Listing, norm, slug, to_int
from .base import Source

BASE = "https://www.icasas.com.ar"
TIPOS = {"departamento": "departamentos", "casa": "casas", "ph": "ph"}
PAGE_SIZE = 30
MAX_DORMITORIOS = 5  # el filtro del sitio ofrece de 1 a 5
AMBIENTES = re.compile(r"\b(\d{1,2}) ?amb(ientes?)?\b")  # sobre texto normalizado


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _meta(li: Tag, prop: str) -> str:
    m = li.select_one(f'meta[itemprop="{prop}"]')
    return (m.get("content") or "").strip() if m else ""


class ICasas(Source):
    name = "icasas"
    label = "iCasas"

    def _url(self, f: Filters) -> str:
        # Belgrano R/C/Chico no existen como zona propia: están dentro de Belgrano. Varias zonas van separadas por coma.
        zonas = list(dict.fromkeys("belgrano" if norm(b).startswith("belgrano") else slug(b) for b in f.barrios))
        filtros: list[str] = []
        # el sitio filtra por dormitorios (cantidad exacta, combinables), no por ambientes: N ambientes ≈ N-1 dormitorios
        if f.ambientes_min and f.ambientes_min > 1:
            hasta = min(MAX_DORMITORIOS, f.ambientes_max - 1) if f.ambientes_max else MAX_DORMITORIOS
            filtros += [f"{n}-dormitorio{'s' if n > 1 else ''}" for n in range(f.ambientes_min - 1, hasta + 1)]
        if f.precio_max and f.moneda == "USD":
            filtros.append(f"{f.precio_min or 0}-{f.precio_max}-price")
        url = f"{BASE}/{f.operacion}/{TIPOS.get(f.tipo, 'departamentos')}/capital-federal"
        url += ("/" + ",".join(zonas) if zonas else "") + ("/f_" + ",".join(filtros) if filtros else "")
        return url + "/o_fecha-actualizacion"  # más nuevos primero

    def search(self, f: Filters) -> Iterable[Listing]:
        url = self._url(f)
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            soup = BeautifulSoup(http.get(url + (f"/p_{page}" if page > 1 else "")).text, "html.parser")
            count, fresh, last = 0, 0, False
            for li in soup.select("ul.listAds > li.serp-snippet, ul.listAds > h4.nearByTitleCss"):
                # cuando se acaban los resultados, el sitio rellena la página con avisos "cercanos" de otras zonas
                if li.name == "h4":
                    last = True
                    break
                count += 1
                a = li.select_one("h2.title a[href]")
                if not a or not li.get("id") or li["id"] in seen:
                    continue
                seen.add(li["id"])
                fresh += 1
                price_text = _text(li.select_one("div.price"))
                price = to_int(price_text)
                barrio = _meta(li, "addressLocality")
                description = _text(li.select_one("p.description"))
                # la tarjeta no trae ambientes como dato: solo se conocen si el texto los menciona
                amb = AMBIENTES.search(norm(f"{_text(a)} {description}"))
                yield Listing(
                    source=self.name,
                    id=li["id"],
                    url=BASE + a["href"],
                    title=_text(a),
                    price=price if price and price > 1 else None,  # "U$S 1" = precio a consultar
                    currency="USD" if "U$S" in price_text.upper() else "ARS",
                    address=_meta(li, "streetAddress"),
                    location=", ".join(x for x in (barrio, _meta(li, "addressRegion")) if x),
                    rooms=int(amb.group(1)) if amb else None,
                    bedrooms=to_int(_text(li.select_one("span.rooms")) or None),  # ícono de cama: son dormitorios
                    bathrooms=to_int(_text(li.select_one("span.bathrooms")) or None),
                    area=to_int(_text(li.select_one("span.areaBuilt")) or None),
                    description=description,
                    image=(li.select_one('section[itemprop="photo"] meta[itemprop="url"]') or {}).get("content"),
                )
            if last or count < PAGE_SIZE or not fresh:
                break
