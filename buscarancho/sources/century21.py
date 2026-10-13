from __future__ import annotations

from typing import Iterable

from .. import http
from ..models import Filters, Listing, norm
from .base import Source

BASE = "https://century21.com.ar"
API = f"{BASE}/api/search"  # el mismo endpoint que usa el scroll infinito de /search (16 avisos por página)
OPS = {"venta": "sell", "alquiler": "rent", "temporal": "temporal"}
TIPOS = {"departamento": "departamento", "casa": "casa", "ph": "ph"}


class Century21(Source):
    name = "century21"
    label = "Century 21"
    max_pages = 12

    def _zonas(self, f: Filters) -> list[str | None]:
        """No hay zonas: `q` es texto libre. Belgrano R/C/Chico salen buscando "Belgrano"."""
        zonas = list(dict.fromkeys("Belgrano" if norm(b).startswith("belgrano") else b for b in f.barrios))
        return zonas or [None]

    def search(self, f: Filters) -> Iterable[Listing]:
        seen: set[str] = set()
        for zona in self._zonas(f):
            params = {"q": zona, "op": OPS.get(f.operacion, "sell"), "type": TIPOS.get(f.tipo, f.tipo)}
            if f.precio_min:
                params["pmin"] = f.precio_min
            if f.precio_max:
                params["pmax"] = f.precio_max
            if f.precio_min or f.precio_max:
                params["currency"] = f.moneda
            params = {k: v for k, v in params.items() if v}
            for page in range(1, self.max_pages + 1):
                data = http.get(API, params={**params, "page": page} if page > 1 else params).json()
                for x in data.get("data", []):
                    pid = str(x["property_id"])
                    if pid in seen or x.get("status") != "active":
                        continue
                    seen.add(pid)
                    yield self._listing(x)
                if page >= (data.get("pagination") or {}).get("total_pages", 0):
                    break

    def _listing(self, x: dict) -> Listing:
        # el barrio viene en addr_neighborhood o en addr_district según la carga, así que van todos
        place = dict.fromkeys(p.strip() for k in ("neighborhood", "subarea", "district", "region") if (p := x.get(f"addr_{k}")) and p.strip())
        street = "" if x.get("addr_hidden") else " ".join(p for k in ("street", "number") if (p := (x.get(f"addr_{k}") or "").strip()))
        area = x.get("covered_square_meters") or x.get("effective_surface_area")
        return Listing(
            source=self.name,
            id=str(x["property_id"]),
            url=f"{BASE}/propiedades/{x['property_id']}",
            title=x.get("title") or "",
            price=int(float(x["price"])) if x.get("price") and not x.get("price_hidden") else None,
            currency=x.get("currency_id"),
            address=street,
            location=", ".join(place),
            rooms=x.get("rooms") or None,
            bedrooms=x.get("bedrooms") or None,
            bathrooms=x.get("bathrooms") or None,
            area=int(float(area)) if area else None,
            garage=True if x.get("garage") else None,  # 0 suele ser "sin cargar", no "sin cochera"
            description=x.get("description") or "",
            image=x.get("image_path") or None,
        )
