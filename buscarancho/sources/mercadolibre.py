from __future__ import annotations

import json
import re
from typing import Iterable

from .. import http
from ..models import Filters, Listing, slug
from .base import Source

BASE = "https://inmuebles.mercadolibre.com.ar"
TIPOS = {"departamento": "departamentos", "casa": "casas", "ph": "ph"}
PAGE_SIZE = 48
# acá "Belgrano" es una zona aparte de sus sub-barrios: hay que pedirlos uno por uno
SUBZONAS = {"belgrano": ["belgrano", "belgrano-c", "belgrano-r", "belgrano-chico", "belgrano-barrancas"]}


def _polycards(html: str) -> list[dict]:
    """Los resultados vienen como objetos "polycard" dentro del estado embebido en la página."""
    out, decoder = [], json.JSONDecoder()
    for m in re.finditer(r'"polycard":(?=\{)', html):
        try:
            out.append(decoder.raw_decode(html, m.end())[0])
        except ValueError:
            continue
    return out


def _range_max(text: str) -> int | None:
    """'4 ambs.' -> 4, '1 a 4 ambs.' -> 4"""
    nums = re.findall(r"\d+", text)
    return int(nums[-1]) if nums else None


class MercadoLibre(Source):
    name = "mercadolibre"
    label = "MercadoLibre"
    max_pages = 4

    def _url(self, f: Filters, barrio: str | None, ambientes: int | None, offset: int) -> str:
        parts = [TIPOS.get(f.tipo, "departamentos"), f.operacion]
        if ambientes:
            parts.append(f"{ambientes}-ambientes")
        parts.append("capital-federal")
        if barrio:
            parts.append(barrio)
        suffix = f"_Desde_{offset + 1}" if offset else ""
        if f.precio_max:
            suffix += f"_PriceRange_{f.precio_min or 0}{f.moneda}-{f.precio_max}{f.moneda}"
        if offset:
            suffix += "_NoIndex_True"
        return f"{BASE}/" + "/".join(parts) + "/" + suffix

    def search(self, f: Filters) -> Iterable[Listing]:
        seen: set[str] = set()
        zonas = list(dict.fromkeys(z for b in f.barrios for z in SUBZONAS.get(slug(b), [slug(b)]))) or [None]
        for barrio, ambientes in ((b, a) for b in zonas for a in f.ambientes()):
            for page in range(self.max_pages):
                cards = _polycards(http.get(self._url(f, barrio, ambientes, page * PAGE_SIZE)).text)
                fresh = 0
                for card in cards:
                    meta = card.get("metadata", {})
                    item_id = meta.get("id")
                    if not item_id or item_id in seen:
                        continue
                    seen.add(item_id)
                    fresh += 1
                    comp = {c.get("id") or c.get("type"): c.get(c.get("type"), {}) for c in card.get("components", [])}
                    # emprendimientos: el precio es "desde" (la unidad más chica), no sirve para filtrar
                    if comp.get("price", {}).get("prefix") or meta.get("domain_id", "").startswith("MLA-DEVELOPMENT"):
                        continue
                    price = comp.get("price", {}).get("current_price", {})
                    attrs = comp.get("attributes_list", {}).get("texts", [])
                    rooms = next((_range_max(t) for t in attrs if "amb" in t), None)
                    baths = next((_range_max(t) for t in attrs if "baño" in t), None)
                    area = next((_range_max(t) for t in attrs if "m²" in t), None)
                    location = comp.get("location", {}).get("text", "")
                    pics = card.get("pictures", {}).get("pictures", [])
                    yield Listing(
                        source=self.name,
                        id=item_id,
                        url="https://" + meta.get("url", "").split("#")[0],
                        title=comp.get("title", {}).get("text", ""),
                        price=price.get("value"),
                        currency=price.get("currency"),
                        address=location.split(",")[0].strip(),
                        location=location,
                        rooms=rooms,
                        bathrooms=baths,
                        area=area,
                        image=f"https://http2.mlstatic.com/D_NQ_NP_{pics[0]['id']}-O.jpg" if pics else None,
                    )
                if fresh < PAGE_SIZE // 2:
                    break
