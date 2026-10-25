#!/usr/bin/env python3
"""Weryfikacja linków do projektów Canva przesyłanych do drukarni.

Projektu Canva nie da się sprawdzić bezpośrednio z linku: strona wymaga
zalogowania i jest renderowana w przeglądarce. Dlatego to narzędzie:
  1. sprawdza, czy link jest właściwego typu (link do współpracy z edycją,
     tak jak wymaga drukarnia),
  2. wyciąga ID projektu (do ewentualnej automatyzacji przez Canva Connect API),
  3. zwraca listę kontrolną dla klienta i kroki dla operatora: eksport
     „PDF do druku” ze spadami -> sprawdzenie PDF (źródło 1) lub obrazu (źródło 2).

Przykład:
  python canva_link.py "https://www.canva.com/design/DAGxxxx/abc123/edit" --product ulotka_a5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import margins as M  # noqa: E402

DESIGN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")
MODES = {"edit", "view", "watch", "present"}
SHORT_HOSTS = {"canva.link", "www.canva.link"}


def parse_canva_link(url: str) -> dict:
    url = url.strip().strip("<>\"'")
    if not re.match(r"^https?://", url):
        url = "https://" + url
    u = urlparse(url)
    host = (u.hostname or "").lower()
    res = {"url": url, "valid": False, "design_id": None, "link_type": None, "findings": []}

    if host in SHORT_HOSTS:
        res["link_type"] = "short"
        res["findings"].append(M.Finding(
            "SPRAWDŹ", "SHORT_LINK",
            "To skrócony link Canva (canva.link). Otwórz go w przeglądarce, żeby zobaczyć pełny "
            "adres projektu (canva.com/design/…), albo poproś klienta o link do współpracy."))
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
    """Lista kontrolna dla klienta – na podstawie instrukcji drukarni dla projektów z Canvy."""
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


def export_via_api(design_id: str):  # pragma: no cover - zaślepka na przyszłość
    """Miejsce na automatyczny eksport przez Canva Connect API (etap 2).

    API udostępnia asynchroniczne zadania eksportu (Create / Get design export job),
    wymaga aplikacji z OAuth i dostępu autoryzowanego konta do projektu.
    Dla drukarni istotne jest też API „Print partner” (tylko dla partnerów Canva, w wersji
    preview). Przed implementacją sprawdź w dokumentacji, czy eksport PDF obsługuje spady:
    https://www.canva.dev/docs/connect/api-reference/exports/
    """
    raise NotImplementedError("Eksport przez Canva Connect API nie jest jeszcze zaimplementowany.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Weryfikacja linku do projektu Canva.")
    ap.add_argument("url")
    ap.add_argument("--product", help="ID produktu z rules.yaml (np. ulotka_a5)")
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    rules = M.load_rules(a.rules)
    product = M.get_product(rules, a.product) if a.product else None
    res = parse_canva_link(a.url)
    findings = M.sort_findings(res.pop("findings"))
    out = {**res, "status": M.overall_status(findings),
           "findings": [f.to_dict() for f in findings],
           "client_checklist": client_checklist(product, rules),
           "operator_steps": OPERATOR_STEPS if res["valid"] else []}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
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
