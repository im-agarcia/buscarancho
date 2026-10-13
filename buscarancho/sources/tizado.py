from __future__ import annotations

import re
from html import unescape
from typing import Iterable

from bs4 import BeautifulSoup

from .. import http
from ..models import Filters, Listing, norm, to_int
from .base import Source

BASE = "https://www.tizado.com"
OPERACIONES = {"venta": "2", "alquiler": "1", "temporario": "3"}
TIPOS = {"departamento": "1", "casa": "2", "ph": "1:8"}
MONEDAS = {"U$S": "USD", "USD": "USD", "$": "ARS"}
CAPITAL = "41"  # id de "Capital Federal" en el árbol de ubicaciones del sitio
PAGE_SIZE = 10


class Tizado(Source):
    name = "tizado"
    label = "Tizado"
    max_pages = 20  # el sitio entrega de a 10 avisos

    def _zonas(self, f: Filters) -> list[str]:
        """ids de las ubicaciones del sitio para los barrios pedidos."""
        html = http.get(f"{BASE}/Ubicacion/SeleccionMasUbicaciones/", params={"id": CAPITAL}).text
        todas = {norm(unescape(label)): i for i, label in re.findall(r'value="(\d+)"\s*/>([^<]+)<', html)}
        zonas: list[str] = []
        for b in f.barrios:
            # solo el nombre exacto: cada zona ya incluye sus subzonas (Belgrano -> Belgrano C, Belgrano Chico) y
            # pedir una zona junto con una subzona suya da error 500. Belgrano R es una zona aparte.
            # Si el barrio no existe como zona se usa la que lo contiene ("Palermo Algo" -> Palermo).
            z = todas.get(norm(b)) or next((i for label, i in todas.items() if norm(b).startswith(label + " ")), None)
            if z and z not in zonas:
                zonas.append(z)
        return zonas

    def _body(self, f: Filters, zonas: list[str]) -> dict:
        # mismos campos que manda el scroll infinito del listado; "null" = filtro sin usar
        # no hay filtro por ambientes, y el de dormitorios descarta los avisos que no los informan: no se usa
        return {
            "Orden": "8",  # más reciente
            "SucursalID": "null",
            "Operacion": OPERACIONES.get(f.operacion, "2"),
            "Producto": TIPOS.get(f.tipo, "1"),
            "Ubicacion": ",".join(zonas) or CAPITAL,
            "PrecioDesde": str(f.precio_min or "") if f.moneda == "USD" else "",
            "PrecioHasta": str(f.precio_max or "") if f.moneda == "USD" else "",
            "IncluirEmprendimientos": "1",  # unidades de obras nuevas, como en las búsquedas del sitio
            "Dormitorios": "",
            "Antiguedad": "",
            "DescripcionBusqueda": "",
            # cochera/balcón no se filtran acá: muchos avisos solo los nombran en la descripción
            **{k: "null" for k in ("ConCochera", "AptoProfesional", "ConBalcon", "ConBalconTerraza", "ConDependencia", "Amoblado", "ConVigilancia")},
            "Mapa": "false",
            "Geolocalizacion": "",
        }

    def search(self, f: Filters) -> Iterable[Listing]:
        zonas = self._zonas(f) if f.barrios else []
        if f.barrios and not zonas:
            raise ValueError(f"Tizado no reconoce los barrios {f.barrios}")
        body = self._body(f, zonas)
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            # devuelve un fragmento HTML con las tarjetas; vacío cuando no hay más
            html = http.post(f"{BASE}/Buscar/CargaMasInmueblesParam", json={**body, "Pagina": page}).text
            cards = BeautifulSoup(html, "html.parser").select("div.property")
            for card in cards:
                a = card.select_one("h2 a[href]")
                m = re.search(r"-(lp\d+)$", a["href"]) if a else None
                if not m or m.group(1) in seen:
                    continue
                seen.add(m.group(1))

                def text(sel: str) -> str:
                    el = card.select_one(sel)
                    return " ".join(el.get_text(" ", strip=True).split()) if el else ""

                price = re.match(r"(U\$S|USD|\$)\s*([\d.]+)", text(".price"))
                location, _, code = text(".location").partition("|")
                # los ambientes solo figuran en la URL de la ficha
                rooms = re.search(r"-(\d+)-ambientes-", a["href"])
                img = card.select_one(".image img[src]")
                street = a.get_text(" ", strip=True)
                yield Listing(
                    source=self.name,
                    id=m.group(1),
                    url=BASE + a["href"],
                    title=" · ".join(p for p in (street, code.strip()) if p),
                    price=to_int(price.group(2)) if price else None,
                    currency=MONEDAS[price.group(1)] if price else None,
                    address=street,
                    location=location.strip(),
                    rooms=int(rooms.group(1)) if rooms else 1 if "-monoambiente-" in a["href"] else None,
                    bedrooms=to_int(text(".bedrooms")),
                    bathrooms=to_int(text(".bathrooms")),
                    area=to_int(text(".area .value")),
                    description=text(".body > p"),
                    image=img["src"] if img else None,
                )
            if len(cards) < PAGE_SIZE:
                break
