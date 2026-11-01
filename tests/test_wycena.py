"""Testy skilla „wycena”.

Offline: lokalny udawany serwer API (kształt odpowiedzi jak w systemie wycen, kwoty
wymyślone – prawdziwego cennika nie trzymamy w publicznym repo).
Na żywo: ustaw GRAFFAI_WYCENA_URL (np. http://localhost:5001/api) przy uruchomionej
aplikacji wycen – wtedy wszystkie wzorce z evals/wycena.yaml są wysyłane do API.
"""
import json
import os
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "wycena" / "scripts"))
import wycena as W  # noqa: E402

CASES = yaml.safe_load((ROOT / "evals" / "wycena.yaml").read_text(encoding="utf-8"))["przypadki"]

PLANO = {"nazwa": "zaproszenie", "format": "100x150", "papier": "kreda mat 300g", "naklad": 100,
         "druk": "4+0", "laminowanie": "-", "zlocenie": "-", "personalizacja": "",
         "wymiar_arkusza": "SRA3", "margines_bok": "5", "margines_gora": "5", "spad": "2.5"}
BOOK = {"type": "saddle_stitched_book", "nazwa": "katalog", "naklad": 50, "format": "A4",
        "orientacja": "pionowa", "druk_okladki": "4+4", "papier_okladki": "kreda mat 300g",
        "wykonczenie_okladki": "brak", "druk_srodka": "4+4", "papier_srodka": "kreda mat 135g",
        "liczba_stron": 16}
COST_KEYS = ["products_price", "cut_price", "ricoh_special_color_price", "confection_price",
             "shipping_price", "subtotal", "rounding", "total"]


# --------------------------------------------------------------------------- udawany serwer
class FakeApi(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/v1/papers"):
            return self._send(200, {"kreda mat 300g": {"group": "gr. A3"}, "Offset 80g": {"group": "gr. A"}})
        self._send(404, {"detail": "Not Found"})

    def do_POST(self):
        order = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeApi.requests.append(order)
        errors = []
        for i, p in enumerate(order["products"]):
            if p.get("papier") == "kreda połysk 300g":
                errors.append({"loc": ["body", "products", i, "plano", "papier"], "type": "enum",
                               "msg": "Input should be " + ", ".join(f"'p{k}'" for k in range(20)),
                               "input": p["papier"]})
            if p.get("type", "plano") == "plano" and not str(p.get("naklad")).isdigit():
                errors.append({"loc": ["body", "products", i, "plano", "naklad"], "type": "value_error",
                               "msg": "Value error, Nakład musi być liczbą całkowitą nieujemną",
                               "input": p.get("naklad")})
        if errors:
            return self._send(422, {"detail": errors})
        has_book = any(p.get("type", "plano") != "plano" for p in order["products"])
        products = []
        for p in order["products"]:
            q = dict(p)
            if q.get("type", "plano") == "plano":
                q.update(arkusze=10, cena="100.40")
            else:
                q["cena"] = None
            products.append(q)
        if has_book:
            costs = {k: None for k in COST_KEYS}
        else:
            n = sum(1 for p in order["products"])
            sub = 100.40 * n + (20 if order.get("shipping_enabled") else 0)
            costs = dict(products_price=f"{100.40 * n:.2f}", cut_price="0.00", ricoh_special_color_price="0",
                         confection_price="0.00", shipping_price="20" if order.get("shipping_enabled") else "0",
                         subtotal=f"{sub:.2f}", rounding="0", total=str(round(sub)))
        self._send(200, {"products": products, "costs": costs})


@pytest.fixture(scope="module")
def api():
    srv = HTTPServer(("127.0.0.1", 0), FakeApi)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/api"
    srv.shutdown()


def write(tmp_path, data, name="z.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def run(api, path, capsys, *extra):
    code = W.main([str(path), "--url", api, *extra])
    return code, capsys.readouterr()


# --------------------------------------------------------------------------- wejście
def test_load_input_accepts_bare_api_order(tmp_path):
    d = W.load_input(write(tmp_path, {"products": [PLANO]}))
    assert d["zamowienie"]["products"][0]["nazwa"] == "zaproszenie"
    assert d["pytania"] == [] and d["zalozenia"] == []


def test_load_input_string_lists_and_missing_products(tmp_path):
    d = W.load_input(write(tmp_path, {"zamowienie": {}, "pytania": "Ile sztuk?"}))
    assert d["zamowienie"]["products"] == [] and d["pytania"] == ["Ile sztuk?"]


@pytest.mark.parametrize("data,msg", [
    ([], "obiekt"),
    ({"cos": 1}, "zamowienie"),
    ({"zamowienie": {"products": [{"type": "plakat"}]}}, "nieznany typ"),
    ({"zamowienie": {"products": ["x"]}}, "nie jest obiektem"),
])
def test_load_input_rejects(tmp_path, data, msg):
    with pytest.raises(ValueError, match=msg):
        W.load_input(write(tmp_path, data))


# --------------------------------------------------------------------------- wycena
def test_full_quote(api, tmp_path, capsys):
    code, out = run(api, write(tmp_path, {"zamowienie": {"products": [PLANO]},
                                          "zalozenia": ["Druk jednostronny"]}), capsys)
    assert code == 0
    assert "100,40 zł" in out.out and "Razem: 100 zł" in out.out
    assert "Druk jednostronny" in out.out


def test_questions_make_partial_result(api, tmp_path, capsys):
    code, out = run(api, write(tmp_path, {"zamowienie": {"products": [PLANO]}, "pytania": ["Jaki papier?"]}), capsys)
    assert code == 1 and "Pytania do klienta" in out.out


def test_book_without_price(api, tmp_path, capsys):
    code, out = run(api, write(tmp_path, {"zamowienie": {"products": [PLANO, BOOK]}}), capsys)
    assert code == 1
    assert "brak ceny" in out.out and "Razem: brak" in out.out


def test_shipping_listed(api, tmp_path, capsys):
    code, out = run(api, write(tmp_path, {"zamowienie": {"products": [PLANO], "shipping_enabled": True}}), capsys)
    assert code == 0 and "Wysyłka: 20 zł" in out.out


def test_no_products_no_request(api, tmp_path, capsys):
    before = len(FakeApi.requests)
    code, out = run(api, write(tmp_path, {"zamowienie": {"products": []}, "pytania": ["Ile sztuk?"]}), capsys)
    assert len(FakeApi.requests) == before
    assert code == 1 and "Brak pozycji do wyceny" in out.out


def test_validation_errors_in_polish(api, tmp_path, capsys):
    bad = dict(PLANO, nazwa="winietka", papier="kreda połysk 300g", naklad="sto")
    code, out = run(api, write(tmp_path, {"zamowienie": {"products": [PLANO, bad]}}), capsys)
    assert code == 2
    assert "Pozycja 2 (winietka): papier – wartość spoza listy dozwolonych" in out.out
    assert "--papers" in out.out and "'p19'" not in out.out          # długa lista skrócona
    assert "Pozycja 2 (winietka): nakład – Nakład musi być liczbą" in out.out


def test_json_output(api, tmp_path, capsys):
    code, out = run(api, write(tmp_path, {"zamowienie": {"products": [PLANO]}, "poza_wycena": ["obraz"]}),
                    capsys, "--json")
    data = json.loads(out.out)
    assert data["wycena"]["costs"]["total"] == "100" and data["poza_wycena"] == ["obraz"]


def test_papers(api, capsys):
    assert W.main(["--papers", "--url", api]) == 0
    assert "kreda mat 300g  [gr. A3]" in capsys.readouterr().out


def test_no_server(tmp_path, capsys):
    code = W.main([str(write(tmp_path, {"products": [PLANO]})), "--url", "http://127.0.0.1:9/api"])
    assert code == 3 and "Brak połączenia" in capsys.readouterr().err


def test_bad_file(tmp_path, capsys):
    p = tmp_path / "z.json"
    p.write_text("{nie json", encoding="utf-8")
    assert W.main([str(p), "--url", "http://127.0.0.1:9/api"]) == 2


def test_url_from_env(monkeypatch):
    monkeypatch.setenv("GRAFFAI_WYCENA_URL", "http://serwer:5001/api/")
    assert W.api_url(None) == "http://serwer:5001/api"
    assert W.api_url("http://x/api") == "http://x/api"


@pytest.mark.parametrize("value,text", [("112.32", "112,32 zł"), ("200", "200 zł"),
                                        ("1234.5", "1 234,50 zł"), (None, "brak ceny")])
def test_money_format(value, text):
    assert W._zl(value) == text


# --------------------------------------------------------------------------- przypadki testowe
def _matches(expected: dict, product: dict) -> bool:
    return all(str(product.get(k)) == str(v) for k, v in expected.items())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_golden_extraction_meets_expectations(case):
    """Wzorcowa ekstrakcja spełnia oczekiwania – pilnuje spójności pliku z przypadkami."""
    exp, gold = case["oczekiwane"], case["wzorzec"]
    products = gold["zamowienie"].get("products", [])
    assert len(products) == len(exp["pozycje"])
    free = list(products)
    for e in exp["pozycje"]:
        hit = next((p for p in free if _matches(e, p)), None)
        assert hit is not None, f"{case['id']}: brak pozycji {e}"
        free.remove(hit)
    for key in ("pytania", "poza_wycena"):
        if key in exp:
            assert bool(gold.get(key)) == exp[key], key
    for k, v in (exp.get("zamowienie") or {}).items():
        assert gold["zamowienie"].get(k, {"order_group": "B"}.get(k, False)) == v, k


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_golden_plano_fields_complete(case):
    required = set(PLANO)
    for p in case["wzorzec"]["zamowienie"].get("products", []):
        if p.get("type", "plano") == "plano":
            assert required <= set(p), f"{case['id']}: brak pól {required - set(p)}"
            assert str(p["naklad"]).isdigit()


# --------------------------------------------------------------------------- na żywo
def _live_url():
    url = os.environ.get("GRAFFAI_WYCENA_URL")
    if not url:
        return None
    try:
        W._request(url.rstrip("/") + "/v1/papers")
        return url.rstrip("/")
    except Exception:
        return None


LIVE = _live_url()


@pytest.mark.skipif(not LIVE, reason="ustaw GRAFFAI_WYCENA_URL przy uruchomionej aplikacji wycen")
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_live_api_accepts_golden(case):
    order = case["wzorzec"]["zamowienie"]
    if not order.get("products"):
        pytest.skip("brak pozycji do wyceny")
    result = W.quote(LIVE, json.loads(json.dumps(order, default=str)))
    for p in result["products"]:
        if p.get("type", "plano") == "plano":
            assert p["cena"] is not None
    if all(p.get("type", "plano") == "plano" for p in order["products"]):
        assert result["costs"]["total"] is not None
