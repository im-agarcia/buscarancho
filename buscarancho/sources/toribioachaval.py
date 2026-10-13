from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup

from .. import http
from ..models import Filters, Listing, norm, to_int
from .base import Source

BASE = "https://www.toribioachaval.com"
TIPOS = {"departamento": "departamentos", "casa": "casas", "ph": "ph"}
MAX_AMB = 4  # el filtro "4-ambientes" del sitio significa "4 o más"; 1 a 3 son exactos


class ToribioAchaval(Source):
    name = "toribioachaval"
    label = "Toribio Achával"

    def __init__(self) -> None:
        self._fichas: dict[str, str] = {}  # url -> texto de la ficha ya abierta

    def _zonas(self, f: Filters) -> list[str]:
        """Slugs de barrio tal como los usa el buscador (salen del autocompletar del sitio).
        Belgrano R/C/Chico no existen como zona propia: caen en la zona cuyo nombre es prefijo."""
        todas: dict[str, str] = {}
        for u in http.get(f"{BASE}/ubicaciones").json():
            kind, _, path = u["Id"].split("|", 2)
            if kind == "B" and path.startswith("capital-federal/"):
                todas[norm(u["label"].split(",")[-1])] = path.split("/")[-1]
        zonas: list[str] = []
        for b in f.barrios:
            nb = norm(b)
            match = max((n for n in todas if nb == n or nb.startswith(n + " ")), key=len, default=None)
            if match is None:
                raise ValueError(f"Toribio Achával no reconoce el barrio '{b}'")
            if todas[match] not in zonas:
                zonas.append(todas[match])
        return zonas

    def _urls(self, f: Filters) -> list[tuple[str, int | None]]:
        """(url, ambientes exactos si la búsqueda los garantiza). Los filtros son segmentos de la ruta."""
        url = f"{BASE}/listado/{TIPOS.get(f.tipo, 'departamentos')}/{f.operacion}/" + ("_o_".join(self._zonas(f)) if f.barrios else "capital-federal")
        precio = f"/precio_{f.precio_min or 0}-{f.precio_max}-{f.moneda}-" if f.precio_max else ""
        if not f.ambientes_min:
            return [(url + precio, None)]
        desde = min(f.ambientes_min, MAX_AMB)
        hasta = min(f.ambientes_max or MAX_AMB, MAX_AMB)
        return [(f"{url}/{n}-ambientes{precio}", n if n < MAX_AMB else None) for n in range(desde, hasta + 1)]

    def search(self, f: Filters) -> Iterable[Listing]:
        seen: set[str] = set()
        budget = self.detail_budget
        for url, ambientes in self._urls(f):
            for page in range(1, self.max_pages + 1):
                html = http.get(url + (f"/page_{page}" if page > 1 else "")).text
                for item in BeautifulSoup(html, "html.parser").select("#resultados_propiedades div.item"):
                    listing = self._card(item, f, ambientes)
                    if not listing or listing.id in seen:
                        continue
                    seen.add(listing.id)
                    # la tarjeta no trae ambientes, cochera, expensas ni descripción: se completan con la ficha
                    if budget > 0:
                        budget -= 1
                        try:
                            self._fill(listing)
                        except http.Blocked:
                            budget = 0
                    yield listing
                if f"/page_{page + 1}\"" not in html:
                    break

    def _card(self, item, f: Filters, ambientes: int | None) -> Listing | None:
        a = item.select_one("a[href*='/propiedades/']")
        if not a or not (m := re.search(r"-(\d+)/?$", a["href"])):
            return None

        def text(sel: str) -> str:
            el = item.select_one(sel)
            return el.get_text(" ", strip=True) if el else ""

        feats: dict[str, int] = {}
        for div in item.select(".superficie > div"):
            top, bottom = div.select_one(".top"), div.select_one(".bottom")
            if top and bottom and (n := re.match(r"\d+", top.get_text(strip=True))):  # "123.56" m2 -> 123
                feats[norm(bottom.get_text(strip=True))[:4]] = int(n.group())
        price = re.match(r"(USD|U\$S|\$)\s*([\d.]+)", text(".precio"))
        img = item.find("img")
        address, barrio = text(".desc"), text(".ubicacion")
        return Listing(
            source=self.name,
            id=m.group(1),
            url=BASE + a["href"],
            title=f"{text('.tipo') or f.tipo.capitalize()} en {f.operacion} en {address}, {barrio}",
            price=to_int(price.group(2)) if price else None,
            currency=("ARS" if price.group(1) == "$" else "USD") if price else None,
            address=address,
            location=f"{barrio}, Capital Federal" if barrio else "",
            rooms=ambientes,
            bedrooms=feats.get("dorm"),
            bathrooms=feats.get("bano"),
            area=feats.get("m2"),
            image=img.get("src") if img else None,
        )

    def _ficha(self, url: str) -> str:
        if url not in self._fichas:
            html = http.get(url).text
            # solo el cuerpo del aviso: el menú del sitio nombra "Cocheras" y confundiría la detección
            start, end = html.find('<span class="precio">'), html.find("AVISO LEGAL")
            self._fichas[url] = http.html_to_text(html[max(start, 0) : end if end > 0 else len(html)])
        return self._fichas[url]

    def _fill(self, listing: Listing) -> None:
        t = self._ficha(listing.url)
        if m := re.search(r"(\d+) ambientes?\b|Ambientes: (\d+)", t):
            listing.rooms = int(m.group(1) or m.group(2))
        if re.search(r"\b[1-9]\d* cocheras?\b|Cochera: [1-9]", t):
            listing.garage = True
        if m := re.search(r"Expensas: \$\s*([\d.]+)", t):
            listing.expenses = f"$ {to_int(m.group(1)):,}".replace(",", ".")
        if m := re.search(r"Descripción (.+?)(?= Características de l| Superficies Aprox| Ver más| Consultar por esta|$)", t):
            listing.description = m.group(1).strip()

    def detail_text(self, listing: Listing) -> str:
        return self._ficha(listing.url)
