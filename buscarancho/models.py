from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field


def norm(text: str | None) -> str:
    """minúsculas, sin acentos, espacios colapsados"""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(text)).strip("-")


def to_int(text) -> int | None:
    """'USD 180.000' -> 180000, '68,80 m²' -> 68"""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    m = re.search(r"\d[\d.]*", str(text))
    return int(m.group().replace(".", "")) if m and m.group().replace(".", "") else None


# nombres alternativos -> el que usan los portales
ALIAS_BARRIOS = {"barrancas de belgrano": "Belgrano Barrancas", "barrancas": "Belgrano Barrancas"}


@dataclass
class Filters:
    operacion: str = "venta"
    tipo: str = "departamento"
    barrios: list[str] = field(default_factory=list)
    ambientes_min: int | None = None
    ambientes_max: int | None = None
    banos_min: int | None = None
    precio_min: int | None = None
    precio_max: int | None = None
    moneda: str = "USD"
    cochera: bool = False
    balcon: bool = False
    # si un aviso no dice nada sobre cochera/balcón: False = se descarta, True = se incluye marcado "sin confirmar"
    incluir_sin_confirmar: bool = False
    fuentes: list[str] = field(default_factory=list)  # vacío = todas

    def ambientes(self, extra: int = 3) -> list[int | None]:
        """Cantidades de ambientes a consultar, para portales que solo filtran por cantidad exacta."""
        if not self.ambientes_min:
            return [None]
        return list(range(self.ambientes_min, (self.ambientes_max or self.ambientes_min + extra) + 1))

    @classmethod
    def from_dict(cls, d: dict) -> "Filters":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        known["barrios"] = list(dict.fromkeys(ALIAS_BARRIOS.get(norm(b), b) for b in known.get("barrios") or []))
        return cls(**known)


@dataclass
class Listing:
    source: str
    id: str
    url: str
    title: str = ""
    price: int | None = None
    currency: str | None = None
    expenses: str | None = None
    address: str = ""
    location: str = ""
    rooms: int | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    area: int | None = None
    garage: bool | None = None
    balcony: bool | None = None
    description: str = ""
    image: str | None = None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    def to_dict(self) -> dict:
        return asdict(self)
