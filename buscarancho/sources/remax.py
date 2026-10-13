from __future__ import annotations

from typing import Iterable

from .. import http
from ..models import Filters, Listing, norm, slug
from .base import Source

API = "https://api-ar.redremax.com/remaxweb-ar/api/listings/findAllWithEntrepreneurships"
TIPOS = {"departamento": "departamentos", "casa": "casas", "ph": "ph"}
PAGE_SIZE = 100


class Remax(Source):
    name = "remax"
    label = "RE/MAX"
    max_pages = 10

    def _landings(self, f: Filters) -> list[str]:
        """La API busca por "landing" (una por zona). Belgrano R/C/Chico están dentro de la de Belgrano."""
        prefix = f"{TIPOS.get(f.tipo, 'departamentos')}-en-{f.operacion}-en-"
        zonas: list[str] = []
        for b in f.barrios or ["ciudad-de-buenos-aires"]:
            z = "belgrano" if norm(b).startswith("belgrano") else slug(b)
            if z not in zonas:
                zonas.append(z)
        # las landings menos conocidas llevan el sufijo -capital-federal
        return [prefix + z + ("" if z in ("belgrano", "palermo", "recoleta", "ciudad-de-buenos-aires") else "-capital-federal") for z in zonas]

    def search(self, f: Filters) -> Iterable[Listing]:
        for landing in self._landings(f):
            for page in range(self.max_pages):
                data = http.get(API, params={"page": page, "pageSize": PAGE_SIZE, "sort": "-createdAt", "landingPath": landing}).json()["data"]
                # una landing inexistente devuelve todo el país en vez de un error
                if data.get("totalItems", 0) > 5000:
                    raise ValueError(f"RE/MAX no reconoce la zona '{landing}'")
                for x in data.get("data", []):
                    if x.get("entrepreneurship") or (x.get("listingStatus") or {}).get("value") != "active":
                        continue
                    photos = x.get("photos") or []
                    expenses = x.get("expensesPrice")
                    yield Listing(
                        source=self.name,
                        id=str(x["id"]),
                        url=f"https://www.remax.com.ar/listings/{x['slug']}",
                        title=x.get("title", ""),
                        price=int(x["price"]) if x.get("price") and x.get("priceExposure", True) else None,
                        currency=(x.get("currency") or {}).get("value"),
                        expenses=f"{(x.get('expensesCurrency') or {}).get('value', '')} {int(expenses):,}".replace(",", ".") if expenses else None,
                        address=x.get("displayAddress", ""),
                        location=x.get("geoLabel") or "",
                        rooms=x.get("totalRooms"),
                        bedrooms=x.get("bedrooms"),
                        bathrooms=x.get("bathrooms"),
                        area=int(x["dimensionCovered"]) if x.get("dimensionCovered") else None,
                        image=f"https://d1acdg20u0pmxj.cloudfront.net/{photos[0]['rawValue']}.jpg" if photos else None,
                    )
                if page + 1 >= data.get("totalPages", 0):
                    break
