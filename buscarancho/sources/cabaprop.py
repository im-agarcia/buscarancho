from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .. import http
from ..models import Filters, Listing, norm
from .base import Source

BASE = "https://cabaprop.com.ar"
API = BASE + "/api/v1"
OPERACIONES = {"venta": 1, "alquiler": 2, "temporario": 3}
TIPOS = {"departamento": 1, "casa": 2, "ph": 3}
MONEDAS = {1: "USD", 2: "ARS"}
PAGE_SIZE = 12  # el mismo que usa el sitio; cada aviso viene completo (~20 KB)


def _slug(title: str) -> str:
    """Igual que el front: la ruta es /propiedad/<id>/<título>, sin pasar a minúsculas."""
    return re.sub(r"[^a-zA-Z0-9\-_~]+", "-", "".join(c for c in unicodedata.normalize("NFD", title) if not unicodedata.combining(c))).strip("-")


class Cabaprop(Source):
    name = "cabaprop"
    label = "Cabaprop"

    def _barrios(self, f: Filters) -> dict[int, str]:
        """id -> nombre de las zonas del sitio. Cada barrio incluye sus subzonas (Belgrano -> Belgrano C, Belgrano R, ...)."""
        todos = {int(b["value"]): b["label"] for b in http.get(f"{API}/utils/barrios-flat").json()}
        wanted = [norm(b) for b in f.barrios]
        return {i: label for i, label in todos.items() if not wanted or any(norm(label) == w or norm(label).startswith(w + " ") for w in wanted)}

    def _body(self, f: Filters, barrios: Iterable[int]) -> dict:
        # ambientes: el 5 significa "5 o más"
        top = min(f.ambientes_max or 5, 5)
        return {
            "operationType": OPERACIONES.get(f.operacion, 1),
            "propertyTypes": [TIPOS.get(f.tipo, 1)],
            "barrios": list(barrios),
            "price": {"currency": f.moneda, "tag": "dolares" if f.moneda == "USD" else "pesos", "min": f.precio_min or "", "max": f.precio_max or ""},
            "surface": {"tag": "superficieTotal", "type": "totalSurface", "min": "", "max": ""},
            "ambiences": list(range(min(f.ambientes_min, 5), top + 1)) if f.ambientes_min else [],
            "bedrooms": [],
            "characteristics": [],
            "bathrooms": min(f.banos_min or 0, 5),  # "N o más"
            "garages": 0,  # no se filtra acá: muchos avisos solo nombran la cochera en la descripción
            "extras": [],
            "antiquity": "",
        }

    def search(self, f: Filters) -> Iterable[Listing]:
        barrios = self._barrios(f)
        if f.barrios and not barrios:
            raise ValueError(f"Cabaprop no reconoce los barrios {f.barrios}")
        body = self._body(f, barrios if f.barrios else [])
        seen: set[str] = set()
        for page in range(self.max_pages):
            # offset es el número de página (desde 0), no de aviso
            data = http.post(f"{API}/properties/find-properties", params={"offset": page, "limit": PAGE_SIZE, "orderBy": "created_at", "sort": "desc"}, json=body).json()
            for x in data.get("result") or []:
                if x["_id"] in seen or x.get("status", "published") != "published":
                    continue
                seen.add(x["_id"])
                loc, price, ch, surface = x.get("location") or {}, x.get("price") or {}, x.get("characteristics") or {}, x.get("surface") or {}
                garage, images = ch.get("garage") or {}, x.get("images") or []
                expenses = price.get("expenses")
                zonas = [barrios[b] for b in loc.get("barrios") or [] if b in barrios]
                yield Listing(
                    source=self.name,
                    id=x["_id"],
                    url=x.get("permalink") or f"{BASE}/propiedad/{x['_id']}/{_slug(x.get('title') or '')}",
                    title=" ".join((x.get("title") or "").split()),
                    price=int(price["total"]) if price.get("total") else None,
                    currency=MONEDAS.get(price.get("currency")),
                    expenses=f"{MONEDAS.get(price.get('expensesCurrency'), 'ARS')} {int(expenses):,}".replace(",", ".") if expenses else None,
                    address=" ".join(str(p) for p in (loc.get("street"), loc.get("number")) if p).title(),
                    location=", ".join(zonas + [loc.get("area_level_2") or "Capital Federal"]),
                    rooms=ch.get("ambience") or None,
                    bedrooms=ch.get("bedrooms") or None,
                    bathrooms=ch.get("bathrooms") or None,
                    area=int(surface.get("coveredSurface") or surface.get("totalSurface") or 0) or None,
                    garage=True if garage.get("active") or garage.get("quantity") else None,
                    description=x.get("description") or "",
                    image=next((i["url"] for i in images if isinstance(i, dict) and i.get("url")), None),
                )
            if (page + 1) * PAGE_SIZE >= data.get("allPropertiesLength", 0):
                break

    def detail_text(self, listing: Listing) -> str:
        # la ficha se arma en el navegador; la descripción completa ya vino en la búsqueda
        return listing.description
