#!/usr/bin/env python3
"""Verification of Canva design links submitted to the print shop.

A Canva design can't be checked directly from its link: the page requires
login and is rendered in the browser. So this tool instead:
  1. checks whether the link is of the right type (an edit-collaboration
     link, as required by the print shop),
  2. extracts the design ID (for possible automation via the Canva Connect API),
  3. returns a checklist for the client and steps for the operator: export
     "Print PDF" with bleed -> check the PDF (source 1) or image (source 2).

Short links (canva.link/...) are expanded to the full design URL by following the
redirect (one HTTP request to canva.link, the design page itself is not loaded).
Without network access the link is reported as SHORT_LINK, to be opened by hand.

Example:
  python canva_link.py "https://www.canva.com/design/DAGxxxx/abc123/edit" --product ulotka_a5
  python canva_link.py "https://canva.link/abc123xyz" --product wizytowka_90x50
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import margins as M  # noqa: E402

DESIGN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")
MODES = {"edit", "view", "watch", "present"}
SHORT_HOSTS = {"canva.link", "www.canva.link"}

RESOLVE_TIMEOUT_S = 10
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 200_000
_DESIGN_URL_RE = re.compile(r"https://(?:www\.)?canva\.com/design/[A-Za-z0-9_-]+(?:/[^\s\"'<>]*)?")

# fetch(url) -> (HTTP status, Location header or None, start of the response body)
Fetch = Callable[[str], "tuple[int, Optional[str], str]"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stops at the first redirect so we read its Location instead of loading the design page."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_fetch(url: str) -> "tuple[int, Optional[str], str]":
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "graffAI-canva-link/1.0"})
    try:
        with opener.open(req, timeout=RESOLVE_TIMEOUT_S) as r:
            body = r.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
            return r.status, r.headers.get("Location"), body
    except urllib.error.HTTPError as e:      # 3xx lands here because redirects are not followed
        return e.code, e.headers.get("Location"), ""


def resolve_short_link(url: str, fetch: Optional[Fetch] = None) -> Optional[str]:
    """Full URL behind a canva.link short link, or None if it can't be resolved.

    Follows HTTP redirects one by one (at most MAX_REDIRECTS) until it leaves canva.link.
    If canva.link answers 200 with an HTML page instead of a redirect, takes the first
    canva.com/design/... URL found in it. Network errors and timeouts give None.
    """
    fetch = fetch or _http_fetch
    current = url
    for _ in range(MAX_REDIRECTS):
        try:
            status, location, body = fetch(current)
        except (OSError, ValueError):            # URLError, timeout, bad URL
            return None
        if location:
            target = urljoin(current, location)
            if (urlparse(target).hostname or "").lower() in SHORT_HOSTS:
                current = target
                continue
            return target
        if status == 200:
            m = _DESIGN_URL_RE.search(html.unescape(body))
            return m.group(0) if m else None
        return None
    return None


def parse_canva_link(url: str, resolve: bool = False, fetch: Optional[Fetch] = None) -> dict:
    """Checks a Canva link. resolve=True expands canva.link short links over the network
    (the CLI does this by default); without it a short link is only reported."""
    url = url.strip().strip("<>\"'")
    if not re.match(r"^https?://", url):
        url = "https://" + url
    u = urlparse(url)
    host = (u.hostname or "").lower()
    res = {"url": url, "valid": False, "design_id": None, "link_type": None, "findings": []}

    if host in SHORT_HOSTS:
        target = resolve_short_link(url, fetch) if resolve else None
        if target:
            full = parse_canva_link(target)
            full["short_url"] = url
            full["findings"].insert(0, M.Finding(
                "INFO", "SHORT_LINK_RESOLVED",
                f"Skrócony link canva.link prowadzi do: {full['url']}"))
            return full
        res["link_type"] = "short"
        res["findings"].append(M.Finding(
            "SPRAWDŹ", "SHORT_LINK",
            ("Nie udało się automatycznie rozwinąć skróconego linku Canva (canva.link) – brak "
             "połączenia albo link wygasł. " if resolve else "To skrócony link Canva (canva.link). ")
            + "Otwórz go w przeglądarce, żeby zobaczyć pełny adres projektu (canva.com/design/…), "
              "albo poproś klienta o link do współpracy."))
        return res
    if not (host == "canva.com" or host.endswith(".canva.com")):
        res["findings"].append(M.Finding("BŁĄD", "NOT_CANVA", "To nie jest link do Canvy."))
        return res

    path = u.path.rstrip("/") or "/"
    if path.startswith(("/templates", "/p/", "/szablony")):
        res["link_type"] = "template"
        res["findings"].append(M.Finding(
            "BŁĄD", "TEMPLATE_LINK",
            "To link do szablonu Canva, a nie do projektu klienta. Potrzebny jest link do "
            "własnego projektu (Udostępnij → Link do współpracy)."))
        return res

    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] != "design" or not DESIGN_ID_RE.match(parts[1]):
        res["findings"].append(M.Finding(
            "BŁĄD", "UNKNOWN_CANVA_LINK",
            "Nie rozpoznano linku jako projektu Canva (oczekiwany adres canva.com/design/…)."))
        return res

    res["valid"] = True
    res["design_id"] = parts[1]
    mode = parts[-1] if parts[-1] in MODES else "unknown"
    res["link_type"] = mode
    if mode == "edit":
        res["findings"].append(M.Finding(
            "INFO", "EDIT_LINK",
            "Link do współpracy z możliwością edycji – zgodnie z wymaganiami drukarni. "
            "Upewnij się, że dostęp jest ustawiony na „Każda osoba, która ma link”."))
    elif mode in ("view", "watch", "present"):
        res["findings"].append(M.Finding(
            "OSTRZEŻENIE", "VIEW_ONLY_LINK",
            "Link tylko do podglądu. Drukarnia potrzebuje linku do współpracy z edycją: "
            "Udostępnij → Link do współpracy → „Każda osoba, która ma link” + „Może edytować” "
            "→ Kopiuj link. Z linku do podglądu nie pobierzemy pliku do druku."))
    else:
        res["findings"].append(M.Finding(
            "SPRAWDŹ", "UNKNOWN_MODE",
            "Nie wiadomo, czy link pozwala na edycję. Poproś o link do współpracy "
            "(„Każda osoba, która ma link” + „Może edytować”)."))
    return res


def client_checklist(product: M.Product | None, rules: dict) -> list:
    """Client checklist - based on the print shop's instructions for Canva designs."""
    b = M.fmt(rules["defaults"]["bleed_mm"])
    s = M.fmt(rules["defaults"]["safe_mm"])
    f = M.fmt(rules["defaults"]["frame_mm"])
    size = (f"{M.fmt(product.trim_w)}×{M.fmt(product.trim_h)} mm" if product
            else "docelowy format (np. A5)")
    items = [
        f"Rozmiar strony ustawiony na format netto: {size} (Zmień rozmiar → Rozmiar niestandardowy).",
        "Włączone spady: Plik → Linijki i prowadnice → Pokaż spady drukarskie.",
        "Tło i zdjęcia, które mają dochodzić do krawędzi, wychodzą POZA czarną linię "
        f"(na obszar spadu, {b} mm z każdej strony).",
        f"Teksty, logo i ważne elementy są min. {s} mm od krawędzi (od czarnej linii do środka).",
        f"Ramki są min. {f} mm od krawędzi.",
    ]
    if product and (product.folds_x or product.folds_y):
        folds = ", ".join(M.fmt(x) for x in product.folds_x + product.folds_y)
        items.append(f"Produkt składany: projekt jako rozkładówka (strona zewnętrzna i wewnętrzna), "
                     f"nie pojedyncze strony. Bigi na {folds} mm – teksty min. {s} mm, "
                     f"ramki min. {f} mm od zgięcia.")
    items.append("Pobieranie: Udostępnij → Pobierz → „PDF do druku”, profil kolorów CMYK, "
                 "zaznaczone „Znaczniki przycięcia i spady”.")
    if product and product.id.startswith("wizytowka"):
        items.append("Wizytówki: drukarnia zaleca przesłanie linku do współpracy zamiast pliku – "
                     "domyślne wizytówki w Canvie mają za niską rozdzielczość i niestandardowy "
                     "format, graficy drukarni to poprawią.")
    if product and product.id.startswith("zaproszenie"):
        items.append("Zaproszenia personalizowane: udostępnij projekt PRZED personalizacją; "
                     "każdego gościa jako osobną (powieloną) stronę.")
    return items


OPERATOR_STEPS = [
    "Otwórz link (zalogowany na konto drukarni) i sprawdź Plik → Linijki i prowadnice → "
    "Pokaż spady drukarskie.",
    "Zweryfikuj rozmiar projektu (Zmień rozmiar) – musi być formatem NETTO produktu.",
    "Pobierz: PDF do druku, CMYK, zaznacz „Znaczniki przycięcia i spady”.",
    "Sprawdź pobrany PDF narzędziem do PDF (źródło 1). Uwaga: PDF ze znacznikami cięcia jest "
    "większy niż format + spady – geometrię brać z TrimBox/BleedBox, nie z MediaBox.",
    "Alternatywnie wyeksportuj PNG/JPG w pełnej rozdzielczości i sprawdź: "
    "check_image.py <plik> --product <id> --preview",
]


def export_via_api(design_id: str):  # pragma: no cover - stub for future work
    """Placeholder for automatic export via the Canva Connect API (stage 2).

    The API offers asynchronous export jobs (Create / Get design export job),
    requires an OAuth app and authorized access to the design's account.
    Also relevant for the print shop is the "Print partner" API (Canva partners only,
    currently in preview). Before implementing, check the docs for whether PDF export
    supports bleed:
    https://www.canva.dev/docs/connect/api-reference/exports/
    """
    raise NotImplementedError("Export via the Canva Connect API is not yet implemented.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Weryfikacja linku do projektu Canva.")
    ap.add_argument("url")
    ap.add_argument("--product", help="ID produktu z rules.yaml (np. ulotka_a5)")
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-resolve", action="store_true",
                    help="nie rozwijaj skróconych linków canva.link (bez połączenia z siecią)")
    a = ap.parse_args(argv)

    rules = M.load_rules(a.rules)
    product = M.get_product(rules, a.product) if a.product else None
    res = parse_canva_link(a.url, resolve=not a.no_resolve)
    findings = M.sort_findings(res.pop("findings"))
    out = {**res, "status": M.overall_status(findings),
           "findings": [f.to_dict() for f in findings],
           "client_checklist": client_checklist(product, rules),
           "operator_steps": OPERATOR_STEPS if res["valid"] else []}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if out.get("short_url"):
            print(f"Skrócony link: {out['short_url']}")
        print(f"Link: {out['url']}\nWYNIK: {out['status']}")
        if out["design_id"]:
            print(f"ID projektu: {out['design_id']} (typ linku: {out['link_type']})")
        for f in out["findings"]:
            print(f"  [{f['severity']}] {f['message']}")
        print("\nLista kontrolna dla klienta:")
        for i, s in enumerate(out["client_checklist"], 1):
            print(f"  {i}. {s}")
        if out["operator_steps"]:
            print("\nKroki dla drukarni:")
            for i, s in enumerate(out["operator_steps"], 1):
                print(f"  {i}. {s}")
    return {"OK": 0, "DO_WERYFIKACJI": 1, "OSTRZEŻENIA": 1, "BŁĘDY": 2}[out["status"]]


if __name__ == "__main__":
    sys.exit(main())
