from __future__ import annotations

import os
import re

import requests

from .models import norm
from .store import Diff


def money(entry: dict, price=None) -> str:
    price = entry.get("price") if price is None else price
    return f"{entry.get('currency') or ''} {price:,}".replace(",", ".").strip() if price else "s/precio"


def dup_key(entry: dict) -> str:
    """Misma dirección (calle + altura) y precio = el mismo departamento publicado en varios portales."""
    m = re.search(r"([a-z .]+?) (\d{2,5})\b", norm(entry.get("address")))
    return f"{m.group(1).strip()} {m.group(2)}|{entry.get('price')}" if m else f"{entry['source']}:{entry['id']}"


def group_duplicates(entries: list[dict]) -> list[list[dict]]:
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(dup_key(e), []).append(e)
    return list(groups.values())


def _line(group: list[dict], labels: dict[str, str]) -> str:
    e = group[0]
    feats = [f"{e['rooms']} amb" if e.get("rooms") else None, f"{e['bathrooms']} baños" if e.get("bathrooms") else None, f"{e['area']} m²" if e.get("area") else None]
    links = " · ".join(f"[{labels.get(x['source'], x['source'])}]({x['url']})" for x in group)
    line = f"- **{money(e)}** — {e.get('address') or e.get('title')}"
    if e.get("location") and norm(e["location"]) != norm(e.get("address")):
        line += f" ({e['location']})"
    line += " — " + ", ".join(x for x in feats if x)
    if e.get("price") and e.get("area"):
        line += f" — {e.get('currency') or ''} {round(e['price'] / e['area']):,}/m²".replace(",", ".")
    if e.get("expenses"):
        line += f" — exp. {e['expenses']}"
    if e.get("sin_confirmar"):
        line += f" — ⚠️ sin confirmar: {', '.join(e['sin_confirmar'])}"
    return f"{line} — {links}"


def markdown(diff: Diff, status: dict[str, dict], labels: dict[str, str], total_active: int, limit: int = 60) -> str:
    out = []
    if diff.new:
        groups = sorted(group_duplicates(diff.new), key=lambda g: g[0].get("price") or 0)
        out.append(f"## 🆕 {len(groups)} propiedades nuevas\n")
        out += [_line(g, labels) for g in groups[:limit]]
        if len(groups) > limit:
            out.append(f"- … y {len(groups) - limit} más")
    if diff.price_changes:
        out.append(f"\n## 💲 {len(diff.price_changes)} cambios de precio\n")
        for e in diff.price_changes:
            arrow = "⬇️" if (e.get("price") or 0) < (e.get("old_price") or 0) else "⬆️"
            out.append(f"- {arrow} {money(e, e.get('old_price'))} → **{money(e)}** — {e.get('address') or e.get('title')} — [{labels.get(e['source'], e['source'])}]({e['url']})")
    if diff.closed:
        out.append(f"\n## 🚫 {len(diff.closed)} dadas de baja\n")
        out += [f"- {money(e)} — {e.get('address') or e.get('title')} ({labels.get(e['source'], e['source'])})" for e in diff.closed[:limit]]
    out.append(f"\n## Portales\n\n{total_active} avisos activos que cumplen el filtro.\n")
    for name, st in status.items():
        out.append(f"- {'✅' if st['ok'] else '❌'} {labels.get(name, name)}: " + (f"{st['found']} encontrados, {st['matched']} cumplen" if st["ok"] else st["error"]))
    return "\n".join(out) + "\n"


def telegram(text: str) -> None:
    """Opcional: se activa definiendo TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    for start in range(0, len(text), 3800):
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[start : start + 3800], "disable_web_page_preview": True},
            timeout=30,
        ).raise_for_status()
