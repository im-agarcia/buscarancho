from __future__ import annotations

import re
import time
from html import unescape
from urllib.parse import urlsplit

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
}
DELAY = 1.5  # segundos entre pedidos al mismo host
HOST_DELAY: dict[str, float] = {}  # hosts que piden ir más despacio (lo completa cada fuente)
CHALLENGE_MARKS = ("Just a moment...", "cf-challenge", "captcha-delivery", "px-captcha", "account-verification")


class Blocked(Exception):
    """El sitio rechazó el pedido (anti-bot). No se intenta saltearlo."""


_session = requests.Session()
_session.headers.update(HEADERS)
_last_hit: dict[str, float] = {}


def get(url: str, *, params: dict | None = None, timeout: int = 30) -> requests.Response:
    host = urlsplit(url).netloc
    wait = HOST_DELAY.get(host, DELAY) - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = _session.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last_error = e
            time.sleep(2 * (attempt + 1))
            continue
        finally:
            _last_hit[host] = time.monotonic()
        if resp.status_code in (401, 403, 429) or "x-amzn-waf-action" in resp.headers or any(m in resp.text[:20000] for m in CHALLENGE_MARKS):
            raise Blocked(f"{host} respondió {resp.status_code} (bloqueo anti-bot)")
        if resp.status_code >= 500:
            last_error = requests.HTTPError(f"{resp.status_code} en {url}")
            time.sleep(2 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp
    raise last_error  # type: ignore[misc]


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))
