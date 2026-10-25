"""Pełne sprawdzenie PDF do druku: format i spady, kolory, marginesy.

Łączy pdf_boxes, pdf_colors i pdf_margins w jeden raport (ten sam układ co
check_image.py ze skilla margin-check).

    python skills/pdf-check/scripts/check_pdf.py plik.pdf --product ulotka_a5 [--preview out/] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdf_boxes import InvalidPdfError, read_boxes
from pdf_colors import REGISTRATION, color_spaces
from pdf_margins import DEFAULT_RENDER_DPI, M, check_margins

EXIT_CODES = {"OK": 0, "DO_WERYFIKACJI": 1, "OSTRZEŻENIA": 1, "BŁĘDY": 2}


def _color_findings(colors) -> list:
    out = []
    if colors.has_rgb:
        where = " i ".join(w for w, used in (("zdjęcia", "RGB" in colors.images),
                                             ("grafika/tekst", "RGB" in colors.vector)) if used)
        out.append(M.Finding("INFO", "RGB",
                             f"Na stronie jest RGB ({where}) – drukarnia przyjmuje RGB, ale kolory w druku "
                             f"(CMYK) mogą być mniej nasycone. Z Canvy: „PDF do druku” w CMYK."))
    if colors.spot_names:
        out.append(M.Finding("SPRAWDŹ", "SPOT_COLOR",
                             f"Kolory dodatkowe: {', '.join(sorted(colors.spot_names))}. Sprawdź, czy to "
                             f"warstwa do uszlachetnienia (złocenie, biały toner) czy pomyłka."))
    unknown = {k for k in set(colors.images) | colors.vector if k in ("Unknown", "Lab", "Pattern")}
    if unknown:
        out.append(M.Finding("INFO", "COLOR_UNRECOGNISED",
                             f"Nie rozpoznano części kolorów ({', '.join(sorted(unknown))}) – "
                             f"sprawdź wizualnie."))
    return out


def _status(findings: list) -> str:
    return M.overall_status(findings)


def check_pdf(path, product=None, render_dpi: float = DEFAULT_RENDER_DPI, preview_dir=None) -> dict:
    """Raport dla PDF. Bez produktu: tylko format, spady i kolory (+ podpowiedź produktu)."""
    path = Path(path) if isinstance(path, str) else path
    geometry = read_boxes(path)
    colors = color_spaces(path)
    margins = check_margins(path, product, render_dpi, preview_dir) if product is not None else None
    rules = M.load_rules()

    report = {"file": str(path), "pages": []}
    if product is not None:
        prod = product if isinstance(product, M.Product) else M.get_product(rules, product)
        report["product"] = {"id": prod.id, "name": prod.name, "trim_mm": [prod.trim_w, prod.trim_h]}

    general = []
    if not geometry:
        general.append(M.Finding("BŁĄD", "NO_PAGES", "PDF nie ma żadnej strony."))
    if product is None and geometry:
        w, h = geometry[0].trim_size
        suggestions = M.suggest_products(rules, w * 100, h * 100)
        general.append(M.Finding("SPRAWDŹ", "PRODUCT_UNKNOWN",
                                 "Nie podano produktu – marginesów nie sprawdzono. "
                                 + (f"Format pasuje do: {', '.join(suggestions)}." if suggestions
                                    else f"Format netto strony 1: {M.fmt(w)}×{M.fmt(h)} mm.")))

    for i, g in enumerate(geometry):
        c = colors[i]
        findings = _color_findings(c)
        page = {
            "page": g.page,
            "trim_mm": list(g.trim_size),
            "bleed_mm": g.bleed_mm,
            "trimbox": g.trim_explicit,
            "crop_marks": g.has_crop_marks,
            "colors": {"images": dict(c.images), "vector": sorted(c.vector - {REGISTRATION}),
                       "spots": sorted(c.spot_names)},
        }
        if margins is not None:
            m = margins[i]
            findings += m.findings
            page["analysed_bleed_mm"] = m.analysed_bleed_mm
            page["render_dpi"] = m.render_dpi
            if m.preview:
                page["preview"] = str(m.preview)
        findings = M.sort_findings(findings)
        page["status"] = _status(findings)
        page["findings"] = [f.to_dict() for f in findings]
        report["pages"].append(page)

    report["general"] = [f.to_dict() for f in M.sort_findings(general)]
    statuses = [p["status"] for p in report["pages"]] + [_status(general)]
    report["status"] = next((s for s in ("BŁĘDY", "OSTRZEŻENIA", "DO_WERYFIKACJI") if s in statuses), "OK")
    return report


def format_text(report: dict) -> str:
    icon = {"BŁĄD": "✖", "OSTRZEŻENIE": "⚠", "SPRAWDŹ": "?", "INFO": "·"}
    lines = [f"Plik: {report['file']}"]
    if "product" in report:
        lines.append(f"Produkt: {report['product']['name']}")
    lines.append(f"WYNIK: {report['status']}")
    if "error" in report:
        lines.append(report["error"])
        return "\n".join(lines)
    lines += [f"  {icon[f['severity']]} [{f['severity']}] {f['message']}" for f in report["general"]]
    for p in report["pages"]:
        w, h = p["trim_mm"]
        lines.append(f"-- strona {p['page']}: {M.fmt(w)}×{M.fmt(h)} mm, "
                     f"znaczniki cięcia: {'tak' if p['crop_marks'] else 'nie'} – {p['status']}")
        lines += [f"  {icon[f['severity']]} [{f['severity']}] {f['message']}" for f in p["findings"]]
        if p.get("preview"):
            lines.append(f"  Podgląd: {p['preview']}")
    return "\n".join(lines)


def _parse_trim(s: str) -> tuple:
    a, b = s.lower().replace("×", "x").replace(",", ".").split("x")
    return float(a), float(b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sprawdzanie PDF do druku: format, spady, kolory, marginesy.")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--product", help="ID produktu z rules.yaml (np. ulotka_a5)")
    ap.add_argument("--trim", type=_parse_trim, help="format netto w mm, np. 100x200")
    ap.add_argument("--folds", help="pozycje bigów w mm od lewej krawędzi, np. 99,198")
    ap.add_argument("--render-dpi", type=float, default=DEFAULT_RENDER_DPI,
                    help="rozdzielczość rasteryzacji do analizy marginesów (72–300)")
    ap.add_argument("--preview", type=Path, nargs="?", const=Path("."),
                    help="katalog na podgląd z naniesionymi liniami (domyślnie bieżący)")
    ap.add_argument("--json", action="store_true", help="wynik w formacie JSON")
    ap.add_argument("--list-products", action="store_true")
    a = ap.parse_args(argv)

    rules = M.load_rules()
    if a.list_products:
        for pid, p in rules["products"].items():
            tw, th = p["trim_mm"]
            print(f"{pid:32s} {p.get('name', pid)}  ({tw:g}×{th:g} mm)")
        return 0
    if not a.file:
        ap.error("podaj plik do sprawdzenia")

    product = None
    if a.product or a.trim:
        try:
            folds = [float(x) for x in a.folds.split(",")] if a.folds else None
            product = M.get_product(rules, a.product, a.trim, folds=folds)
        except (KeyError, ValueError) as exc:
            print(str(exc).strip("'\""), file=sys.stderr)
            return 3

    try:
        report = check_pdf(a.file, product, a.render_dpi, a.preview)
    except (FileNotFoundError, IsADirectoryError, InvalidPdfError) as exc:
        report = {"file": a.file, "status": "NIE_DA_SIĘ_SPRAWDZIĆ", "error": str(exc)}
    print(json.dumps(report, ensure_ascii=False, indent=2) if a.json else format_text(report))
    return EXIT_CODES.get(report["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
