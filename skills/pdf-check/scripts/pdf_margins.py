"""Spady, strefa bezpieczeństwa, ramki i bigi w PDF.

Strona jest rasteryzowana (pypdfium2) dokładnie w obszarze netto + spad – znaczniki
cięcia poza spadem nie trafiają do analizy. Sama analiza to ten sam silnik co dla
plików graficznych (margin-check/scripts/margins.py), więc kody wyników są wspólne.

    python skills/pdf-check/scripts/pdf_margins.py plik.pdf ulotka_a5 [--preview out/]
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium

from pdf_boxes import PT_TO_MM, InvalidPdfError, read_boxes

# Silnik marginesów żyje w skillu margin-check (wspólny dla obrazów i PDF).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "margin-check" / "scripts"))
import margins as M  # noqa: E402

DEFAULT_RENDER_DPI = 200
# Powyżej ~300 dpi silnik margins.py gubi tekst blisko granicy 3 mm (gęstość krawędzi
# w pasie maleje z rozdzielczością) – dlatego górna granica 300.
MIN_RENDER_DPI, MAX_RENDER_DPI = 72, 300
MAX_RENDER_PIXELS = 40_000_000     # jak w check_image – większe strony renderujemy rzadziej
SIZE_TOLERANCE_MM = 0.5            # format netto zgodny z produktem z tą dokładnością
NO_BLEED_MM = 0.3                  # spad mniejszy = brak spadu


@dataclass
class PageMargins:
    page: int                      # numer strony od 1
    trim_size: tuple               # format netto strony (mm), po obrocie
    bleed_mm: dict                 # spad w pliku z każdej strony (mm)
    analysed_bleed_mm: float       # spad, z jakim strona była sprawdzana
    render_dpi: float              # rozdzielczość rasteryzacji (nie rozdzielczość zdjęć!)
    status: str                    # OK | OSTRZEŻENIA | DO_WERYFIKACJI | BŁĘDY
    findings: list = field(default_factory=list)   # list[margins.Finding], najgorsze pierwsze
    preview: Path | None = None

    @property
    def codes(self) -> set:
        return {f.code for f in self.findings}


def _validate_dpi(render_dpi) -> float:
    if isinstance(render_dpi, bool) or not isinstance(render_dpi, (int, float)):
        raise TypeError(f"render_dpi musi być liczbą, jest: {render_dpi!r}")
    if math.isnan(render_dpi) or not MIN_RENDER_DPI <= render_dpi <= MAX_RENDER_DPI:
        raise ValueError(f"render_dpi musi być w zakresie {MIN_RENDER_DPI}–{MAX_RENDER_DPI}, jest: {render_dpi}")
    return float(render_dpi)


def _resolve_product(product) -> M.Product:
    if isinstance(product, M.Product):
        return product
    if isinstance(product, str):
        return M.get_product(M.load_rules(), product)    # KeyError dla nieznanego id
    raise TypeError(f"product musi być id z rules.yaml albo margins.Product, jest: {type(product).__name__}")


def _oriented(product: M.Product, size: tuple) -> M.Product:
    """Produkt obrócony do orientacji strony (wizytówka pionowa itp.)."""
    w, h = size
    if product.trim_w != product.trim_h and (w > h) != (product.trim_w > product.trim_h):
        return product.rotated()
    return product


def _same_size(a: tuple, w: float, h: float) -> bool:
    return abs(a[0] - w) <= SIZE_TOLERANCE_MM and abs(a[1] - h) <= SIZE_TOLERANCE_MM


def _page_bleed(g, prod: M.Product) -> tuple:
    """Spad do analizy + uwagi o spadzie. None = strona nie pasuje do produktu."""
    notes = []
    if not g.trim_explicit:
        # Bez TrimBox strona to albo sam format netto, albo netto + spad.
        if _same_size(g.trim_size, prod.trim_w, prod.trim_h):
            return 0.0, notes
        if _same_size(g.trim_size, prod.trim_w + 2 * prod.bleed_mm, prod.trim_h + 2 * prod.bleed_mm):
            notes.append(M.Finding("INFO", "TRIMBOX_MISSING",
                                   f"PDF nie ma TrimBox – rozmiar strony pasuje do formatu ze spadami, "
                                   f"przyjęto spad {M.fmt(prod.bleed_mm)} mm."))
            return -prod.bleed_mm, notes        # minus: spad jest wewnątrz strony, nie poza TrimBox
        return None, notes

    if not _same_size(g.trim_size, prod.trim_w, prod.trim_h):
        return None, notes
    sides = g.bleed_mm.values()
    smallest, largest = min(sides), max(sides)
    if smallest < NO_BLEED_MM:
        return 0.0, notes
    if smallest < prod.bleed_mm - NO_BLEED_MM:
        notes.append(M.Finding("OSTRZEŻENIE", "BLEED_SIZE",
                               f"Spad w pliku: {M.fmt(smallest)} mm (wymagane {M.fmt(prod.bleed_mm)} mm)."))
    if largest - smallest > NO_BLEED_MM:
        notes.append(M.Finding("INFO", "BLEED_ASYMMETRIC",
                               f"Spad nierówny: od {M.fmt(smallest)} do {M.fmt(largest)} mm – "
                               f"sprawdzono z najmniejszym."))
    return min(smallest, prod.bleed_mm), notes


def _render(pdf_page, g, bleed_mm: float, inside_page: bool, dpi: float, media_origin: tuple):
    """Rasteryzuje obszar netto ± spad. Zwraca obraz PIL (RGB)."""
    if inside_page:     # brak TrimBox: cała strona = netto + spad
        box = g.media
        l, b, r, t = box.x0, box.y0, box.x1, box.y1
    else:
        l, b = g.trim.x0 - bleed_mm, g.trim.y0 - bleed_mm
        r, t = g.trim.x1 + bleed_mm, g.trim.y1 + bleed_mm
    ox, oy = media_origin
    # CropBox ogranicza rysowany obszar (przed obrotem strony) – znaczniki cięcia odpadają.
    pdf_page.set_cropbox(ox + l / PT_TO_MM, oy + b / PT_TO_MM, ox + r / PT_TO_MM, oy + t / PT_TO_MM)
    bitmap = pdf_page.render(scale=dpi / 72, fill_color=(255, 255, 255, 255),
                             draw_annots=False, may_draw_forms=False)
    return bitmap.to_pil().convert("RGB")


def _check_page(pdf_page, g, product: M.Product, dpi: float, preview_dir) -> PageMargins:
    prod = _oriented(product, g.trim_size)
    bleed, findings = _page_bleed(g, prod)
    if bleed is None:
        w, h = g.trim_size
        findings.append(M.Finding(
            "BŁĄD", "FORMAT_MISMATCH",
            f"Format netto strony {M.fmt(w)}×{M.fmt(h)} mm nie pasuje do produktu {product.name} "
            f"({M.fmt(prod.trim_w)}×{M.fmt(prod.trim_h)} mm)."))
        return PageMargins(g.page, g.trim_size, g.bleed_mm, 0.0, dpi, "BŁĘDY", findings)

    inside_page = bleed < 0
    bleed = abs(bleed)
    w_mm, h_mm = prod.trim_w + 2 * bleed, prod.trim_h + 2 * bleed
    pixels = (w_mm / M.MM_PER_INCH * dpi) * (h_mm / M.MM_PER_INCH * dpi)
    if pixels > MAX_RENDER_PIXELS:
        dpi = dpi * (MAX_RENDER_PIXELS / pixels) ** 0.5
        findings.append(M.Finding("INFO", "RENDER_DPI_REDUCED",
                                  f"Duży format – stronę sprawdzono w {dpi:.0f} dpi."))

    left, bottom = pdf_page.get_mediabox()[:2]
    image = _render(pdf_page, g, bleed, inside_page, dpi, (left, bottom))
    layout = M.layout_from_known(image.width, image.height, prod, bleed)
    analysis = M.analyze_raster(np.asarray(image, dtype=np.uint8), layout, prod)
    findings += analysis

    preview = None
    if preview_dir is not None:
        from check_image import make_preview    # Pillow-owe rysowanie podglądu z margin-check
        preview = Path(preview_dir) / f"strona_{g.page}_podglad.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        make_preview(image, layout, prod, analysis, preview)

    return PageMargins(g.page, g.trim_size, g.bleed_mm, bleed, round(dpi, 1),
                       M.overall_status(findings), M.sort_findings(findings), preview)


def check_margins(path, product, render_dpi: float = DEFAULT_RENDER_DPI,
                  preview_dir=None) -> list:
    """Sprawdza marginesy każdej strony PDF względem produktu. Zwraca list[PageMargins]."""
    dpi = _validate_dpi(render_dpi)
    product = _resolve_product(product)
    geometry = read_boxes(path)            # waliduje ścieżkę, plik i hasło
    if not geometry:                       # pdfium nie otwiera PDF bez stron
        return []
    try:
        doc = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        raise InvalidPdfError(f"pdfium nie otworzył {Path(path).name}: {e}") from e
    try:
        return [_check_page(doc[g.page - 1], g, product, dpi, preview_dir) for g in geometry]
    finally:
        doc.close()


def format_text(pages: list) -> str:
    icon = {"BŁĄD": "✖", "OSTRZEŻENIE": "⚠", "SPRAWDŹ": "?", "INFO": "·"}
    lines = []
    for p in pages:
        w, h = p.trim_size
        lines.append(f"strona {p.page}: {M.fmt(w)}×{M.fmt(h)} mm, spad {M.fmt(p.analysed_bleed_mm)} mm"
                     f" – {p.status}")
        lines += [f"  {icon[f.severity]} {f.message}" for f in p.findings]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("product", help="id produktu z rules.yaml, np. ulotka_a5")
    ap.add_argument("--dpi", type=float, default=DEFAULT_RENDER_DPI)
    ap.add_argument("--preview", type=Path)
    a = ap.parse_args(argv)
    pages = check_margins(a.pdf, a.product, a.dpi, a.preview)
    print(format_text(pages))
    return 1 if any(p.status == "BŁĘDY" for p in pages) else 0


if __name__ == "__main__":
    sys.exit(main())
