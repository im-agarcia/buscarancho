from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import Listing

MISSES_TO_CLOSE = 3  # corridas seguidas sin verlo antes de darlo de baja


@dataclass
class Diff:
    new: list[dict] = field(default_factory=list)
    price_changes: list[dict] = field(default_factory=list)  # incluye "old_price"
    closed: list[dict] = field(default_factory=list)


class Store:
    """Historial en un JSON versionado: avisos que cumplieron el filtro y caché de fichas ya revisadas."""

    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {}
        self.listings: dict[str, dict] = data.get("listings", {})
        # cochera/balcón/baños leídos de la ficha, para no volver a pedirla en cada corrida
        self.checked: dict[str, dict] = data.get("checked", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"listings": self.listings, "checked": self.checked}, ensure_ascii=False, indent=1, sort_keys=True) + "\n")

    def update(self, matched: list[tuple[Listing, list[str]]], ok_sources: set[str], now: str) -> Diff:
        diff = Diff()
        seen = set()
        for listing, pending in matched:
            key = listing.key
            seen.add(key)
            prev = self.listings.get(key)
            entry = {**listing.to_dict(), "sin_confirmar": pending, "last_seen": now, "active": True, "misses": 0}
            if prev is None or not prev.get("active", True):
                entry["first_seen"] = prev["first_seen"] if prev else now
                entry["price_history"] = (prev or {}).get("price_history", []) + [{"date": now, "price": listing.price}]
                # los que reaparecen tras una baja no se avisan de nuevo
                if prev is None:
                    diff.new.append(entry)
            else:
                entry["first_seen"] = prev["first_seen"]
                entry["price_history"] = prev.get("price_history", [])
                if prev.get("price") != listing.price:
                    entry["price_history"] = entry["price_history"] + [{"date": now, "price": listing.price}]
                    diff.price_changes.append({**entry, "old_price": prev.get("price")})
            self.listings[key] = entry
        for key, entry in self.listings.items():
            # si el portal falló en esta corrida no se puede saber si el aviso sigue publicado
            if key in seen or not entry.get("active", True) or entry["source"] not in ok_sources:
                continue
            entry["misses"] = entry.get("misses", 0) + 1
            if entry["misses"] >= MISSES_TO_CLOSE:
                entry["active"] = False
                diff.closed.append(entry)
        return diff
