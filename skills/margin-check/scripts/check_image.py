#!/usr/bin/env python3
"""Sprawdza plik graficzny (JPG, PNG, TIFF…) pod kątem spadów, marginesów i ramek.

Przykłady:
  python check_image.py ulotka.jpg --product ulotka_a5
  python check_image.py wizytowka.tif --product wizytowka_90x50 --json
  python check_image.py projekt.png --trim 100x200 --dpi 300 --preview podglad.png
  python check_image.py --list-products

Kody wyjścia: 0 = OK, 1 = ostrzeżenia / do weryfikacji, 2 = błędy, 3 = nie da się sprawdzić.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageSequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import margins as M  # noqa: E402

Image.MAX_IMAGE_PIXELS = 400_000_000
MAX_ANALYSIS_PIXELS = 40_000_000       # większe obrazy są zmniejszane do analizy
MAX_PAGES = 20


# --------------------------------------------------------------------------- #
# Wczytywanie
# --------------------------------------------------------------------------- #
def to_rgb(img: Image.Image) -> tuple:
    """Konwersja do RGB na białym tle. Zwraca (obraz RGB, lista uwag)."""
    notes = []
    mode = img.mode
    if mode in ("I;16", "I;16B", "I;16L", "I"):
        arr = np.asarray(img, dtype=np.float64)
        mx = 65535.0 if arr.max() > 255 else 255.0
        img = Image.fromarray((arr / mx * 255).clip(0, 255).astype(np.uint8), "L")
        notes.append("Obraz 16-bitowy – do analizy przeskalowany do 8 bitów.")
    if img.mode == "P":
        img = img.convert("RGBA")
    if img.mode in ("RGBA", "LA"):
        alpha = np.asarray(img.getchannel("A"))
        if alpha.min() < 250:
            share = float((alpha < 250).mean()) * 100
            notes.append(f"Plik ma przezroczystość ({share:.0f}% powierzchni) – w druku te "
                         f"miejsca będą kolorem papieru. Do analizy przyjęto białe tło.")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    return img.convert("RGB"), notes


def read_pages(path: Path) -> list:
    img = Image.open(path)
    pages = []
    for i, frame in enumerate(ImageSequence.Iterator(img)):
        if i >= MAX_PAGES:
            break
        pages.append(frame.copy())
    return pages, img


def meta_dpi(img: Image.Image):
    dpi = img.info.get("dpi")
    if dpi:
        try:
            return float(dpi[0]), float(dpi[1])
        except (TypeError, ValueError, IndexError):
            return None
    return None


# --------------------------------------------------------------------------- #
# Podgląd
# --------------------------------------------------------------------------- #
COL = {
    "trim": (220, 30, 30), "safe": (0, 160, 70), "frame": (255, 140, 0),
    "fold": (40, 90, 230), "BŁĄD": (220, 0, 0), "OSTRZEŻENIE": (230, 0, 200),
    "SPRAWDŹ": (0, 170, 220),
}


FONT_CANDIDATES = [
    "DejaVuSans.ttf",                                        # Linux (często dostępny)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",          # macOS
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",                            # Windows
    "LiberationSans-Regular.ttf",
]
_ASCII = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _font(size: int):
    """Zwraca (font, czy_obsługuje_polskie_znaki)."""
    for cand in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(cand, size), True
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size), False
    except TypeError:
        return ImageFont.load_default(), False


def _dashed_rect(draw, box, color, width, dash):
    x0, y0, x1, y1 = box
    for (a, b) in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                   ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        _dashed_line(draw, a, b, color, width, dash)


def _dashed_line(draw, a, b, color, width, dash):
    (x0, y0), (x1, y1) = a, b
    length = max(abs(x1 - x0), abs(y1 - y0))
    if length == 0:
        return
    n = int(length // dash)
    for i in range(0, n, 2):
        t0, t1 = i / n, min(1, (i + 1) / n)
        draw.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                   (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)], fill=color, width=width)


def make_preview(rgb: Image.Image, layout: M.Layout, product: M.Product,
                 findings: list, out: Path, max_side: int = 1600) -> None:
    W, H = rgb.size
    k = min(1.0, max_side / max(W, H))
    im = rgb.resize((max(1, int(W * k)), max(1, int(H * k))), Image.LANCZOS) if k < 1 else rgb.copy()
    w, h = im.size
    ppx = layout.dpi_x / M.MM_PER_INCH * k
    ppy = layout.dpi_y / M.MM_PER_INCH * k
    bx, by = layout.bleed_mm * ppx, layout.bleed_mm * ppy

    over = Image.new("RGBA", im.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    if layout.has_bleed:      # spad przyciemniony na czerwono
        od.rectangle([0, 0, w, by], fill=(220, 30, 30, 70))
        od.rectangle([0, h - by, w, h], fill=(220, 30, 30, 70))
        od.rectangle([0, by, bx, h - by], fill=(220, 30, 30, 70))
        od.rectangle([w - bx, by, w, h - by], fill=(220, 30, 30, 70))
    for f in findings:
        for (x0, y0, x1, y1) in f.boxes_px:
            c = COL.get(f.severity, (255, 0, 255))
            od.rectangle([x0 * k, y0 * k, x1 * k, y1 * k], fill=c + (60,), outline=c + (255,),
                         width=max(2, int(w / 400)))
    im = Image.alpha_composite(im.convert("RGBA"), over).convert("RGB")
    d = ImageDraw.Draw(im)
    lw = max(1, int(w / 600))
    dash = max(6, int(w / 120))
    trim = (bx, by, w - bx - 1, h - by - 1)
    d.rectangle(trim, outline=COL["trim"], width=lw)
    s = product.safe_mm
    _dashed_rect(d, (bx + s * ppx, by + s * ppy, w - bx - s * ppx, h - by - s * ppy),
                 COL["safe"], lw, dash)
    fr = product.frame_mm
    _dashed_rect(d, (bx + fr * ppx, by + fr * ppy, w - bx - fr * ppx, h - by - fr * ppy),
                 COL["frame"], lw, dash // 2)
    for pos in product.folds_x:
        x = bx + pos * ppx
        _dashed_line(d, (x, 0), (x, h), COL["fold"], lw + 1, dash)
    for pos in product.folds_y:
        y = by + pos * ppy
        _dashed_line(d, (0, y), (w, y), COL["fold"], lw + 1, dash)

    # legenda pod obrazem
    fs = max(12, int(w / 70))
    font, unicode_ok = _font(fs)
    items = [("linia cięcia", COL["trim"]), (f"strefa bezp. {M.fmt(s)} mm", COL["safe"]),
             (f"ramki {M.fmt(fr)} mm", COL["frame"])]
    if product.folds_x or product.folds_y:
        items.append(("big", COL["fold"]))
    items += [("błąd", COL["BŁĄD"]), ("ostrzeżenie", COL["OSTRZEŻENIE"]),
              ("sprawdź", COL["SPRAWDŹ"])]
    leg_h = int(fs * 2.2)
    canvas = Image.new("RGB", (w, h + leg_h), (255, 255, 255))
    canvas.paste(im, (0, 0))
    cd = ImageDraw.Draw(canvas)
    x = int(fs * 0.6)
    for label, c in items:
        if not unicode_ok:
            label = label.translate(_ASCII)
        cd.rectangle([x, h + fs * 0.6, x + fs, h + fs * 1.6], fill=c)
        x += int(fs * 1.4)
        cd.text((x, h + fs * 0.55), label, fill=(30, 30, 30), font=font)
        x += int(cd.textlength(label, font=font) + fs * 1.2)
    canvas.save(out)


# --------------------------------------------------------------------------- #
# Sprawdzenie pliku
# --------------------------------------------------------------------------- #
def check_file(path: Path, product: M.Product, rules: dict, preview_dir: Path | None = None,
               ) -> dict:
    report = {"file": str(path), "product": {"id": product.id, "name": product.name,
                                             "trim_mm": [product.trim_w, product.trim_h],
                                             "min_dpi": product.min_dpi},
              "pages": []}
    general = []
    ext = path.suffix.lower().lstrip(".")
    if ext not in rules["accepted_formats"]:
        sev = "OSTRZEŻENIE" if ext == "png" else "BŁĄD"
        general.append(M.Finding(sev, "FORMAT_NOT_ACCEPTED",
                                 f"Format .{ext} nie jest na liście akceptowanych przez drukarnię "
                                 f"({', '.join(rules['accepted_formats'])}). Poproś o JPG, TIFF "
                                 f"lub PDF."))
    try:
        pages, src = read_pages(path)
    except Exception as exc:  # noqa: BLE001
        report["status"] = "NIE_DA_SIĘ_SPRAWDZIĆ"
        report["error"] = f"Nie udało się otworzyć pliku: {exc}"
        return report

    report["color_mode"] = src.mode
    if src.mode == "CMYK":
        general.append(M.Finding("INFO", "CMYK", "Plik w przestrzeni CMYK."))
    elif src.mode in ("RGB", "RGBA", "P"):
        general.append(M.Finding("INFO", "RGB", "Plik w RGB – drukarnia przyjmuje RGB, ale kolory "
                                                "w druku (CMYK) mogą być mniej nasycone."))
    if len(pages) > 1:
        general.append(M.Finding("INFO", "MULTIPAGE",
                                 f"Plik wielostronicowy – sprawdzono {len(pages)} stron(y)."))

    for i, page in enumerate(pages, 1):
        page_findings = []
        rgb, notes = to_rgb(page)
        page_findings += [M.Finding("INFO", "IMAGE_NOTE", n) for n in notes]
        px_w, px_h = rgb.size
        mdpi = meta_dpi(page) or meta_dpi(src)
        layout, prod = M.detect_layout(px_w, px_h, product, mdpi)
        pinfo = {"page": i, "px": [px_w, px_h], "meta_dpi": mdpi}
        if layout is None:
            sugg = M.suggest_products(rules, px_w, px_h)
            msg = (f"Proporcje pliku ({px_w}×{px_h} px) nie pasują do produktu "
                   f"{product.name} – ani ze spadami ({M.fmt(product.trim_w + 2 * product.bleed_mm)}×"
                   f"{M.fmt(product.trim_h + 2 * product.bleed_mm)} mm), ani bez nich "
                   f"({M.fmt(product.trim_w)}×{M.fmt(product.trim_h)} mm).")
            if sugg:
                msg += " Proporcjami pasuje do: " + ", ".join(sugg) + "."
            if product.folds_x:
                msg += " Produkt składany wymaga rozkładówki (wszystkie panele w jednym pliku)."
            page_findings.append(M.Finding("BŁĄD", "FORMAT_MISMATCH", msg))
            pinfo["findings"] = [f.to_dict() for f in M.sort_findings(page_findings)]
            pinfo["status"] = "BŁĘDY"
            report["pages"].append(pinfo)
            continue

        if mdpi and layout.method == "aspect":
            page_findings.append(M.Finding(
                "INFO", "META_DPI_IGNORED",
                f"Metadane pliku podają {mdpi[0]:.0f} dpi, co nie zgadza się z formatem – "
                f"rozdzielczość policzono z wymiarów produktu."))
        if layout.ambiguous:
            page_findings.append(M.Finding(
                "SPRAWDŹ", "LAYOUT_AMBIGUOUS",
                "Proporcje pliku pasują prawie tak samo do formatu ze spadami i bez – "
                "nie da się tego pewnie rozstrzygnąć bez poprawnych metadanych DPI."))
        if layout.has_bleed and abs(layout.bleed_mm - product.bleed_mm) > 0.3:
            sev = "OSTRZEŻENIE" if layout.bleed_mm < product.bleed_mm else "INFO"
            page_findings.append(M.Finding(
                sev, "BLEED_SIZE",
                f"Spad w pliku: ok. {M.fmt(layout.bleed_mm)} mm (wymagane {M.fmt(product.bleed_mm)} mm)."))
        if layout.rotated:
            page_findings.append(M.Finding("INFO", "ROTATED",
                                           "Plik w orientacji obróconej względem produktu – "
                                           "sprawdzono w orientacji pliku."))
        page_findings.append(M.Finding(
            "INFO", "LAYOUT",
            f"Rozpoznano: {'format netto + spady' if layout.has_bleed else 'format netto, bez spadów'}"
            f" ({M.fmt(prod.trim_w + 2 * layout.bleed_mm)}×{M.fmt(prod.trim_h + 2 * layout.bleed_mm)} mm)."))
        page_findings += M.check_resolution(layout, prod)

        # analiza (z ewentualnym zmniejszeniem bardzo dużych obrazów)
        work, wl = rgb, layout
        if px_w * px_h > MAX_ANALYSIS_PIXELS:
            k = (MAX_ANALYSIS_PIXELS / (px_w * px_h)) ** 0.5
            work = rgb.resize((int(px_w * k), int(px_h * k)), Image.LANCZOS)
            wl = M.Layout(work.size[0], work.size[1], layout.dpi_x * k, layout.dpi_y * k,
                          layout.bleed_mm, layout.rotated, layout.method)
        arr = np.asarray(work, dtype=np.uint8)
        analysis = M.analyze_raster(arr, wl, prod)
        page_findings += analysis

        pinfo["layout"] = {"bleed_mm": layout.bleed_mm, "dpi": round(layout.dpi),
                           "method": layout.method, "rotated": layout.rotated}
        if preview_dir is not None:
            suffix = f"_s{i}" if len(pages) > 1 else ""
            pv = preview_dir / f"{path.stem}{suffix}_podglad.png"
            make_preview(work, wl, prod, analysis, pv)
            pinfo["preview"] = str(pv)
        pinfo["status"] = M.overall_status(page_findings)
        pinfo["findings"] = [f.to_dict() for f in M.sort_findings(page_findings)]
        report["pages"].append(pinfo)

    report["general"] = [f.to_dict() for f in M.sort_findings(general)]
    statuses = [p["status"] for p in report["pages"]] + [M.overall_status(general)]
    for s in ("BŁĘDY", "OSTRZEŻENIA", "DO_WERYFIKACJI"):
        if s in statuses:
            report["status"] = s
            break
    else:
        report["status"] = "OK"
    return report


def format_text(report: dict) -> str:
    icon = {"BŁĄD": "✖", "OSTRZEŻENIE": "⚠", "SPRAWDŹ": "?", "INFO": "·"}
    lines = [f"Plik: {report['file']}",
             f"Produkt: {report['product']['name']}",
             f"WYNIK: {report['status']}"]
    if "error" in report:
        lines.append(report["error"])
        return "\n".join(lines)
    for f in report.get("general", []):
        lines.append(f"  {icon[f['severity']]} [{f['severity']}] {f['message']}")
    for p in report["pages"]:
        if len(report["pages"]) > 1:
            lines.append(f"-- strona {p['page']}: {p['status']}")
        for f in p["findings"]:
            lines.append(f"  {icon[f['severity']]} [{f['severity']}] {f['message']}")
        if p.get("preview"):
            lines.append(f"  Podgląd: {p['preview']}")
    return "\n".join(lines)


def parse_trim(s: str) -> tuple:
    a, b = s.lower().replace("×", "x").replace(",", ".").split("x")
    return float(a), float(b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sprawdzanie spadów i marginesów pliku graficznego.")
    ap.add_argument("file", nargs="?", type=Path)
    ap.add_argument("--product", help="ID produktu z rules.yaml (np. ulotka_a5)")
    ap.add_argument("--trim", type=parse_trim, help="format netto w mm, np. 100x200")
    ap.add_argument("--dpi", type=int, help="wymagana rozdzielczość (nadpisuje regułę)")
    ap.add_argument("--folds", help="pozycje bigów w mm od lewej krawędzi, np. 99,198")
    ap.add_argument("--rules", type=Path, help="ścieżka do rules.yaml")
    ap.add_argument("--preview", type=Path, nargs="?", const=Path("."),
                    help="katalog na podgląd z naniesionymi liniami (domyślnie bieżący)")
    ap.add_argument("--json", action="store_true", help="wynik w formacie JSON")
    ap.add_argument("--list-products", action="store_true")
    a = ap.parse_args(argv)

    rules = M.load_rules(a.rules)
    if a.list_products:
        for pid, p in rules["products"].items():
            tw, th = p["trim_mm"]
            print(f"{pid:32s} {p.get('name', pid)}  ({tw:g}×{th:g} mm)")
        return 0
    if not a.file:
        ap.error("podaj plik do sprawdzenia")
    if not a.file.exists():
        print(f"Brak pliku: {a.file}", file=sys.stderr)
        return 3
    folds = [float(x) for x in a.folds.split(",")] if a.folds else None
    try:
        product = M.get_product(rules, a.product, a.trim, a.dpi, folds)
    except (KeyError, ValueError) as exc:
        print(str(exc).strip("'\""), file=sys.stderr)
        return 3

    if a.preview is not None:
        a.preview.mkdir(parents=True, exist_ok=True)
    report = check_file(a.file, product, rules, a.preview)
    print(json.dumps(report, ensure_ascii=False, indent=2) if a.json else format_text(report))
    return {"OK": 0, "DO_WERYFIKACJI": 1, "OSTRZEŻENIA": 1, "BŁĘDY": 2}.get(report["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
