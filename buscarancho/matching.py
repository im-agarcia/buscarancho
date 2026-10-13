from __future__ import annotations

import re

from .models import Filters, Listing, norm

# sobre texto normalizado (minúsculas, sin acentos)
GARAGE = re.compile(r"\b(cocheras?|garages?|garajes?|estacionamiento)\b")
GARAGE_NO = re.compile(r"\b(sin|no (tiene|posee|cuenta con|incluye)) (cochera|garage|garaje|estacionamiento)|\bcocheras?:? (0|no)\b")
BALCONY = re.compile(r"\bbalcon(es)?\b")
BALCONY_NO = re.compile(r"\b(sin|no (tiene|posee|cuenta con)) balcon|\bbalcon(es)?:? (0|no)\b")
BATHS = re.compile(r"\b(\d) banos?\b|\bbanos?:? (\d)\b")


def detect(text: str, yes: re.Pattern, no: re.Pattern) -> bool | None:
    if no.search(text):
        return False
    return True if yes.search(text) else None


def fill_from_text(listing: Listing, text: str) -> None:
    """Completa cochera/balcón/baños que la tarjeta no informó, leyendo texto libre."""
    text = norm(text)
    if listing.garage is None:
        listing.garage = detect(text, GARAGE, GARAGE_NO)
    if listing.balcony is None:
        listing.balcony = detect(text, BALCONY, BALCONY_NO)
    if listing.bathrooms is None and (m := BATHS.search(text)):
        listing.bathrooms = int(m.group(1) or m.group(2))


def reject_reason(listing: Listing, f: Filters, check_barrio: bool = True) -> str | None:
    """Motivo de descarte según los datos conocidos; None si (hasta donde se sabe) cumple."""
    if listing.price is None:
        return "sin precio"
    if listing.currency and listing.currency != f.moneda:
        return f"precio en {listing.currency}"
    if f.precio_max and listing.price > f.precio_max:
        return "precio mayor al máximo"
    if f.precio_min and listing.price < f.precio_min:
        return "precio menor al mínimo"
    if listing.rooms is not None:
        if f.ambientes_min and listing.rooms < f.ambientes_min:
            return "menos ambientes"
        if f.ambientes_max and listing.rooms > f.ambientes_max:
            return "más ambientes"
    if f.banos_min and listing.bathrooms is not None and listing.bathrooms < f.banos_min:
        return "menos baños"
    if check_barrio and f.barrios and listing.location and not any(norm(b) in norm(listing.location) for b in f.barrios):
        return "otro barrio"
    if f.cochera and listing.garage is False:
        return "sin cochera"
    if f.balcon and listing.balcony is False:
        return "sin balcón"
    return None


def unconfirmed(listing: Listing, f: Filters) -> list[str]:
    """Requisitos que el aviso no permite confirmar."""
    out = []
    if f.ambientes_min and listing.rooms is None:
        out.append("ambientes")
    if f.banos_min and listing.bathrooms is None:
        out.append("baños")
    if f.cochera and listing.garage is None:
        out.append("cochera")
    if f.balcon and listing.balcony is None:
        out.append("balcón")
    return out
