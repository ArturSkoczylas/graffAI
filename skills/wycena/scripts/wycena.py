#!/usr/bin/env python3
"""Wycena zamówienia w systemie wycen drukarni (API POST /v1/quote).

Wejście: plik JSON przygotowany przez Claude'a z maila klienta:
  {"zamowienie": {...zamówienie w formacie API...},
   "zalozenia": [...], "pytania": [...], "poza_wycena": [...]}
Można też podać samo zamówienie w formacie API (obiekt z kluczem "products").

  python wycena.py zamowienie.json             # podsumowanie dla pracownika
  python wycena.py zamowienie.json --json      # odpowiedź API + uwagi jako JSON
  python wycena.py --papers                    # nazwy papierów akceptowane przez system

Adres API: --url albo zmienna GRAFFAI_WYCENA_URL (domyślnie http://localhost:5001/api).
Kody wyjścia: 0 wycenione, 1 częściowo (bez ceny / pytania do klienta),
2 błąd danych (HTTP 422), 3 brak połączenia lub błąd serwera.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_URL = "http://localhost:5001/api"
TIMEOUT_S = 30

FIELD_NAMES = {
    "nazwa": "nazwa", "format": "format", "papier": "papier", "naklad": "nakład",
    "druk": "druk", "laminowanie": "laminowanie", "zlocenie": "złocenie",
    "personalizacja": "personalizacja", "wymiar_arkusza": "wymiar arkusza",
    "margines_bok": "margines boczny", "margines_gora": "margines górny", "spad": "spad",
    "papier_okladki": "papier okładki", "papier_srodka": "papier środka",
    "druk_okladki": "druk okładki", "druk_srodka": "druk środka",
    "wykonczenie_okladki": "wykończenie okładki", "liczba_stron": "liczba stron",
    "liczba_stron_srodka": "liczba stron środka", "krotszy_bok": "krótszy bok",
    "dluzszy_bok": "dłuższy bok", "orientacja": "orientacja", "kolor_wyklejki": "kolor wyklejki",
    "order_group": "grupa zamówienia", "matrix_price": "koszt matrycy",
    "confection_quantity": "konfekcjonowanie", "products": "lista produktów",
}
PRODUCT_TYPES = {"plano", "softcover_book", "hardcover_book", "saddle_stitched_book"}


class ApiError(Exception):
    def __init__(self, status: int, payload):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.payload = payload


# --------------------------------------------------------------------------- API
def api_url(cli_url: str | None) -> str:
    return (cli_url or os.environ.get("GRAFFAI_WYCENA_URL") or DEFAULT_URL).rstrip("/")


LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _opener(url: str):
    """Do aplikacji uruchomionej lokalnie łączymy się bezpośrednio, z pominięciem proxy."""
    host = urllib.request.urlparse(url).hostname or ""
    if host in LOCAL_HOSTS:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _request(url: str, data: dict | None = None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if body else "GET",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with _opener(url).open(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except (ValueError, UnicodeDecodeError):
            payload = None
        raise ApiError(e.code, payload) from None


def get_papers(base: str) -> dict:
    return _request(f"{base}/v1/papers")


def quote(base: str, order: dict) -> dict:
    return _request(f"{base}/v1/quote", order)


# --------------------------------------------------------------------------- wejście
def load_input(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Plik musi zawierać obiekt JSON.")
    if "zamowienie" not in data:
        if "products" in data:          # samo zamówienie w formacie API
            data = {"zamowienie": data}
        else:
            raise ValueError('Brak klucza "zamowienie" (albo "products").')
    order = data["zamowienie"] or {}
    if not isinstance(order, dict):
        raise ValueError('"zamowienie" musi być obiektem.')
    order.setdefault("products", [])
    for i, p in enumerate(order["products"], 1):
        if not isinstance(p, dict):
            raise ValueError(f"Pozycja {i} nie jest obiektem.")
        t = p.get("type", "plano")
        if t not in PRODUCT_TYPES:
            raise ValueError(f"Pozycja {i}: nieznany typ „{t}” (dozwolone: {', '.join(sorted(PRODUCT_TYPES))}).")
    for key in ("zalozenia", "pytania", "poza_wycena"):
        val = data.get(key) or []
        data[key] = [val] if isinstance(val, str) else list(val)
    data["zamowienie"] = order
    return data


# --------------------------------------------------------------------------- błędy 422
def describe_errors(payload, order: dict) -> list[str]:
    """Błędy walidacji API jako zdania po polsku: „Pozycja 2 (winietka): papier – …”."""
    out = []
    details = (payload or {}).get("detail") if isinstance(payload, dict) else None
    if not isinstance(details, list):
        return [f"Odpowiedź serwera: {payload!r}"]
    products = order.get("products") or []
    for d in details:
        loc = [x for x in d.get("loc", []) if x != "body"]
        msg = str(d.get("msg", "")).removeprefix("Value error, ")
        where = "Zamówienie"
        field = None
        if len(loc) >= 2 and loc[0] == "products" and isinstance(loc[1], int):
            idx = loc[1]
            name = products[idx].get("nazwa") if idx < len(products) else None
            where = f"Pozycja {idx + 1}" + (f" ({name})" if name else "")
            rest = [x for x in loc[2:] if x not in PRODUCT_TYPES]
            field = rest[0] if rest else None
        elif loc:
            field = loc[0]
        label = FIELD_NAMES.get(field, field) if field else None
        if msg.startswith("Input should be") and msg.count("'") > 16:   # długa lista dozwolonych wartości
            msg = "wartość spoza listy dozwolonych" + (
                " – nazwy papierów: python wycena.py --papers" if field and "papier" in str(field) else "")
        inp = d.get("input")
        extra = f" (podano: {inp!r})" if inp is not None and not isinstance(inp, (dict, list)) else ""
        out.append(f"{where}" + (f": {label}" if label else "") + f" – {msg}{extra}")
    return out


# --------------------------------------------------------------------------- podsumowanie
def _zl(value) -> str:
    if value is None:
        return "brak ceny"
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    q = d.quantize(Decimal("0.01"))
    txt = f"{q:,.2f}".replace(",", " ").replace(".", ",")
    return txt.removesuffix(",00") + " zł"


def _product_line(i: int, p: dict) -> str:
    t = p.get("type", "plano")
    if t == "plano":
        extras = []
        if p.get("laminowanie") not in (None, "-"):
            extras.append(f"laminowanie {p['laminowanie']}")
        if p.get("zlocenie") not in (None, "-"):
            extras.append(f"złocenie {p['zlocenie']}")
        if p.get("personalizacja"):
            extras.append(f"personalizacja: {p['personalizacja']}")
        if p.get("iecho"):
            extras.append("wycinanie iEcho")
        if p.get("ricoh_special_color"):
            extras.append("kolor specjalny Ricoh")
        desc = (f"{p.get('format')}, {p.get('papier')}, druk {p.get('druk')}"
                + (", " + ", ".join(extras) if extras else ""))
        sheets = f", {p['arkusze']} ark. SRA3" if p.get("arkusze") is not None else ""
        return f"{i}. {p.get('nazwa')} – {p.get('naklad')} szt. ({desc}{sheets}): {_zl(p.get('cena'))}"
    kind = {"softcover_book": "książka klejona, miękka oprawa",
            "hardcover_book": "książka, twarda oprawa",
            "saddle_stitched_book": "broszura szyta"}[t]
    pages = p.get("liczba_stron") or p.get("liczba_stron_srodka")
    return f"{i}. {p.get('nazwa')} – {p.get('naklad')} szt. ({kind}, {pages} str.): {_zl(p.get('cena'))}"


def summarize(data: dict, result: dict | None, errors: list[str] | None = None) -> str:
    lines = ["WYCENA ZAMÓWIENIA (do sprawdzenia przez pracownika)", ""]
    if errors:
        lines += ["Nie udało się wycenić – popraw dane:"] + [f"  ✖ {e}" for e in errors] + [""]
    if result:
        lines.append("Pozycje:")
        for i, p in enumerate(result.get("products", []), 1):
            lines.append("  " + _product_line(i, p))
        c = result.get("costs") or {}
        lines.append("")
        if c.get("total") is None:
            lines.append("Razem: brak – zamówienie zawiera pozycje, których system jeszcze nie wycenia.")
        else:
            for key, label in (("cut_price", "Wycinanie iEcho"), ("ricoh_special_color_price", "Kolory specjalne Ricoh"),
                               ("confection_price", "Konfekcjonowanie"), ("shipping_price", "Wysyłka")):
                if c.get(key) not in (None, "0", "0.00"):
                    lines.append(f"  {label}: {_zl(c[key])}")
            lines.append(f"Razem: {_zl(c['total'])}  (suma pozycji i usług {_zl(c.get('subtotal'))}, "
                         f"zaokrąglenie do pełnych zł)")
    elif not errors:
        lines.append("Brak pozycji do wyceny.")
    for key, title in (("zalozenia", "Założenia (zweryfikuj przed wysłaniem ceny)"),
                       ("pytania", "Pytania do klienta"),
                       ("poza_wycena", "Poza wyceną systemu")):
        if data.get(key):
            lines += ["", title + ":"] + [f"  • {x}" for x in data[key]]
    return "\n".join(lines)


def exit_code(data: dict, result: dict | None) -> int:
    if result is None:
        return 1
    partial = (result.get("costs") or {}).get("total") is None or bool(data.get("pytania"))
    return 1 if partial else 0


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Wycena zamówienia przez API systemu wycen drukarni.")
    ap.add_argument("plik", nargs="?", type=Path, help="JSON z zamówieniem (format w SKILL.md)")
    ap.add_argument("--url", help=f"adres API (domyślnie $GRAFFAI_WYCENA_URL lub {DEFAULT_URL})")
    ap.add_argument("--json", action="store_true", help="wynik jako JSON")
    ap.add_argument("--papers", action="store_true", help="wypisz papiery dostępne w systemie")
    a = ap.parse_args(argv)
    base = api_url(a.url)

    try:
        if a.papers:
            papers = get_papers(base)
            if a.json:
                print(json.dumps(sorted(papers), ensure_ascii=False, indent=2))
            else:
                for name in sorted(papers, key=str.lower):
                    print(f"{name}  [{(papers[name] or {}).get('group', '?')}]")
            return 0
        if not a.plik:
            ap.error("podaj plik z zamówieniem albo --papers")
        try:
            data = load_input(a.plik)
        except (OSError, ValueError) as e:
            print(f"Błędny plik zamówienia: {e}", file=sys.stderr)
            return 2

        result, errors = None, None
        if data["zamowienie"]["products"]:
            try:
                result = quote(base, data["zamowienie"])
            except ApiError as e:
                if e.status == 422:
                    errors = describe_errors(e.payload, data["zamowienie"])
                else:
                    print(f"Błąd serwera wycen: HTTP {e.status}", file=sys.stderr)
                    return 3
        if a.json:
            print(json.dumps({"wycena": result, "bledy": errors, "zalozenia": data["zalozenia"],
                              "pytania": data["pytania"], "poza_wycena": data["poza_wycena"]},
                             ensure_ascii=False, indent=2))
        else:
            print(summarize(data, result, errors))
        return 2 if errors else exit_code(data, result)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        print(f"Brak połączenia z systemem wycen ({base}): {reason}. "
              f"Uruchom aplikację wycen albo ustaw GRAFFAI_WYCENA_URL.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
