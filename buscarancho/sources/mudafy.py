from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup

from .. import http
from ..models import Filters, Listing, norm, slug, to_int
from .base import Source

BASE = "https://mudafy.com.ar"
TIPOS = {"departamento": "departamentos", "casa": "casas", "ph": "ph"}
# cada dato de la tarjeta se identifica por su ícono
ICONS = {"lucide-maximize-2": "area", "lucide-layout-grid": "rooms", "lucide-bed-double": "bedrooms", "lucide-bath": "bathrooms", "lucide-car": "garages"}


class Mudafy(Source):
    name = "mudafy"
    label = "Mudafy"

    def _url(self, f: Filters, ambientes: int | None) -> str:
        # Belgrano R/C/Chico no existen como zona propia: están dentro de Belgrano
        zonas = list(dict.fromkeys("belgrano" if norm(b).startswith("belgrano") else slug(b) for b in f.barrios))
        url = f"{BASE}/{f.operacion}/{TIPOS.get(f.tipo, 'departamentos')}/"
        url += "_o_".join("caba-" + z for z in zonas) if zonas else "caba"
        return url + (f"/{ambientes}-ambientes" if ambientes else "")

    def search(self, f: Filters) -> Iterable[Listing]:
        seen: set[str] = set()
        for ambientes in f.ambientes():
            yield from self._search(self._url(f, ambientes), seen)

    def _search(self, url: str, seen: set[str]) -> Iterable[Listing]:
        for page in range(1, self.max_pages + 1):
            soup = BeautifulSoup(http.get(url + (f"/{page}-p" if page > 1 else "")).text, "html.parser")
            fresh = 0
            for a in soup.select('a[href^="/departamentos/"], a[href^="/casas/"], a[href^="/ph/"]'):
                h3 = a.find("h3")
                href = a["href"]
                if not h3 or href in seen:
                    continue
                seen.add(href)
                fresh += 1
                feats = {}
                for span in a.select("span"):
                    svg = span.find("svg")
                    kind = next((v for k, v in ICONS.items() if svg and k in (svg.get("class") or [])), None)
                    if kind:
                        feats[kind] = to_int(span.get_text(strip=True))
                texts = [p.get_text(" ", strip=True) for p in a.find_all("p")]
                price = next((re.match(r"(USD|ARS|\$)\s*([\d.]+)", t) for t in texts if re.match(r"(USD|ARS|\$)\s*[\d.]+", t)), None)
                h2 = a.find("h2")
                img = a.find_previous("img")
                yield Listing(
                    source=self.name,
                    id=href.rsplit("-", 1)[-1],
                    url=BASE + href,
                    title=f"{h2.get_text(strip=True) if h2 else ''} · {h3.get_text(strip=True)}",
                    price=to_int(price.group(2)) if price else None,
                    currency={"$": "ARS"}.get(price.group(1), price.group(1)) if price else None,
                    expenses=next((t.replace("Expensas ", "") for t in texts if t.startswith("Expensas")), None),
                    address=h3.get_text(strip=True),
                    location=h2.get_text(strip=True).split("·")[-1].strip() if h2 else "",
                    rooms=feats.get("rooms"),
                    bedrooms=feats.get("bedrooms"),
                    bathrooms=feats.get("bathrooms"),
                    area=feats.get("area"),
                    garage=True if feats.get("garages") else None,
                    description=next((t for t in texts if len(t) > 60), ""),
                    image=img.get("src") if img else None,
                )
            if fresh < 20:
                break
