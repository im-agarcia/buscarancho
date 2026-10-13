from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import http, matching, report
from .models import Filters, Listing
from .sources import all_sources
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def load_filters(path: Path) -> Filters:
    """Con PANEL_URL definido usa los filtros guardados desde el formulario; si no, filters.json."""
    panel = os.environ.get("PANEL_URL")
    if panel:
        try:
            data = requests.get(panel.rstrip("/") + "/api/filters", timeout=20).json()
            if data:
                return Filters.from_dict(data)
        except (requests.RequestException, ValueError) as e:
            print(f"! no pude leer los filtros del panel ({e}); uso {path.name}", file=sys.stderr)
    return Filters.from_dict(json.loads(path.read_text()))


def push_panel(store: Store, status: dict, now: str) -> None:
    panel, token = os.environ.get("PANEL_URL"), os.environ.get("PANEL_TOKEN")
    if not (panel and token):
        return
    active = [e for e in store.listings.values() if e.get("active", True)]
    requests.put(
        panel.rstrip("/") + "/api/listings",
        json={"updated": now, "status": status, "listings": active},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    ).raise_for_status()


def run_source(src, f: Filters, store: Store) -> tuple[list[tuple[Listing, list[str]]], int]:
    matched, found, budget = [], 0, src.detail_budget
    discarded: Counter[str] = Counter()
    for listing in src.search(f):
        found += 1
        matching.fill_from_text(listing, f"{listing.title} {listing.description}")
        if reason := matching.reject_reason(listing, f, src.check_barrio):
            discarded[reason] += 1
            continue
        if matching.unconfirmed(listing, f):
            cached = store.checked.get(listing.key)
            if cached is None and budget > 0:
                budget -= 1
                try:
                    matching.fill_from_text(listing, src.detail_text(listing))
                except http.Blocked:
                    budget = 0  # el portal frenó las fichas: no se insiste
                except requests.RequestException:
                    pass
                else:
                    cached = store.checked[listing.key] = {"garage": listing.garage, "balcony": listing.balcony, "bathrooms": listing.bathrooms}
            if cached:
                for k, v in cached.items():
                    if getattr(listing, k) is None:
                        setattr(listing, k, v)
            if reason := matching.reject_reason(listing, f, src.check_barrio):
                discarded[reason + " (ficha)"] += 1
                continue
        pending = matching.unconfirmed(listing, f)
        if pending and not f.incluir_sin_confirmar:
            discarded["sin confirmar: " + ", ".join(pending)] += 1
            continue
        matched.append((listing, pending))
    print(f"  {src.name} descartes: {dict(discarded.most_common())}", file=sys.stderr)
    return matched, found


def main() -> int:
    ap = argparse.ArgumentParser(prog="buscarancho", description="Busca propiedades en varios portales y avisa las novedades.")
    ap.add_argument("--filters", type=Path, default=ROOT / "filters.json")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--only", help="portales a consultar, separados por coma")
    ap.add_argument("--dry-run", action="store_true", help="no guarda el historial ni notifica")
    args = ap.parse_args()

    f = load_filters(args.filters)
    sources = all_sources()
    wanted = args.only.split(",") if args.only else (f.fuentes or list(sources))
    now = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%Y-%m-%d %H:%M")
    store = Store(args.data / "listings.json")

    matched, status = [], {}
    for name in wanted:
        if name not in sources:
            status[name] = {"ok": False, "error": "portal desconocido"}
            continue
        try:
            got, found = run_source(sources[name], f, store)
        except http.Blocked as e:
            status[name] = {"ok": False, "error": str(e)}
        except Exception as e:  # un portal roto no frena a los demás
            status[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
        else:
            matched += got
            status[name] = {"ok": True, "found": found, "matched": len(got)}
        print(f"{name}: {status[name]}", file=sys.stderr)

    diff = store.update(matched, {n for n, s in status.items() if s["ok"]}, now)
    active = sum(1 for e in store.listings.values() if e.get("active", True))
    labels = {n: s.label for n, s in sources.items()}
    text = f"# Buscarancho — {now}\n\n" + report.markdown(diff, status, labels, active)
    has_news = bool(diff.new or diff.price_changes)
    print(text)

    if not args.dry_run:
        store.save()
        (args.data / "ultima_corrida.md").write_text(text)
        if has_news:
            report.telegram(text)
        push_panel(store, status, now)
        if out := os.environ.get("GITHUB_OUTPUT"):
            with open(out, "a") as fh:
                fh.write(f"novedades={'true' if has_news else 'false'}\n")
                fh.write(f"titulo={len(diff.new)} nuevas, {len(diff.price_changes)} cambios de precio — {now}\n")
    return 0 if any(s["ok"] for s in status.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
