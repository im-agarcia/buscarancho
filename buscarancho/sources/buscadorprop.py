from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup

from .. import http
from ..models import Filters, Listing, norm, slug, to_int
from .base import Source

BASE = "https://www.buscadorprop.com.ar"
TIPOS = {"departamento": "departamentos", "casa": "casas", "ph": "ph"}
# zonas de CABA cuyo slug no sale del nombre (el resto es slug(nombre): belgrano, belgrano-r, nunez...)
ZONAS = {"saavedra": "saavedra-capital", "tribunales": "caba-tribunales", "abasto": "abasto-capital", "versalles": "versailles"}
PAGE_SIZE = 20


class BuscadorProp(Source):
    name = "buscadorprop"
    label = "BuscadorProp"

    def _zonas(self, f: Filters) -> list[str]:
        """Belgrano y Belgrano R son zonas propias; Belgrano C/Chico/Barrancas no existen y caen en Belgrano."""
        zonas = []
        for b in f.barrios:
            z = slug(b)
            z = "belgrano" if z.startswith("belgrano") and z != "belgrano-r" else ZONAS.get(z, z)
            if z not in zonas:
                zonas.append(z)
        return zonas

    def _url(self, f: Filters) -> str:
        """Todo va en el slug: tipo-operacion-ambientes-baños-zonas-precio-orden (los filtros de cantidad son exactos y se acumulan)."""
        parts = [TIPOS.get(f.tipo, "departamentos"), f.operacion]
        ambientes = [f"{n}-ambientes" if n <= 4 else "mas-de-4-ambientes" for n in f.ambientes() if n]
        if f.ambientes_min and not f.ambientes_max:
            ambientes.append("mas-de-4-ambientes")
        parts += dict.fromkeys(ambientes)
        if f.banos_min and f.banos_min > 1:
            parts += [f"{n}-banos" for n in range(f.banos_min, 4)] + ["mas-de-3-banos"]
        parts += self._zonas(f) or ["caba"]
        moneda = "pesos" if f.moneda == "ARS" else "dolares"  # el portal convierte los avisos publicados en la otra moneda
        if f.precio_min and f.precio_max:
            parts.append(f"de-{f.precio_min}-a-{f.precio_max}-{moneda}")
        elif f.precio_min or f.precio_max:
            parts.append(f"{'desde' if f.precio_min else 'hasta'}-{f.precio_min or f.precio_max}-{moneda}")
        return f"{BASE}/{'-'.join(parts)}-mas-nuevas"

    def search(self, f: Filters) -> Iterable[Listing]:
        url, zonas, seen = self._url(f), self._zonas(f), set()
        for page in range(1, self.max_pages + 1):
            soup = BeautifulSoup(http.get(url + (f"-pagina-{page}" if page > 1 else "")).text, "html.parser")
            # una zona que el portal no reconoce se ignora (o redirige a todo CABA) en vez de dar error
            if page == 1 and len(soup.select('.filters__labels__item[data-type="localidad"]')) != len(zonas):
                raise ValueError(f"BuscadorProp no reconoce alguna zona de {zonas}")
            cards = soup.select("#listadoPropiedades div.card-prop")
            for card in cards:
                a = card.select_one('a.card-prop__link[href^="/propiedad/"]')
                if not a:
                    continue
                id_ = a["href"].split("/")[-1].split("-")[0]
                if id_ in seen:
                    continue
                seen.add(id_)

                def text(sel: str) -> str:
                    el = card.select_one(sel)
                    return el.get_text(" ", strip=True) if el else ""

                def feat(word: str) -> int | None:
                    m = re.search(rf"(\d+)\s+{word}", norm(text(".card-prop__body__arriba__high")))
                    return int(m.group(1)) if m else None

                price = re.match(r"(USD|U\$S|\$)\s*([\d.]+)", text(".card-prop__precio__precios__actual"))
                # "Calle 1400, Barrio, Ciudad A. de Buenos Aires" (la calle puede faltar)
                place = [p.strip() for p in text(".card-prop__direccion span").split(",")]
                boton = card.select_one("button[data-cochera]")
                yield Listing(
                    source=self.name,
                    id=id_,
                    url=BASE + a["href"],
                    title=text("h2"),
                    price=to_int(price.group(2)) if price else None,
                    currency=("ARS" if price.group(1) == "$" else "USD") if price else None,
                    expenses=text(".card-prop__precio-expensas").lstrip("+ ").replace(" expensas", "") or text(".card-prop__sin-expensas") or None,
                    address=", ".join(place[:-2]),
                    location=", ".join(place[-2:]),
                    rooms=feat("ambientes?"),
                    bedrooms=feat("dormitorios?"),
                    bathrooms=feat("banos?"),
                    garage=True if boton and boton.get("data-cochera") else None,  # vacío = no informa
                    image=a.get("data-foto"),
                )
            if len(cards) < PAGE_SIZE:
                break
