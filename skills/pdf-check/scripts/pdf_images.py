"""Rozdzielczość obrazów osadzonych w PDF: efektywne DPI po przeskalowaniu na stronie.

Moduł tylko mierzy – nie ocenia. Liczy DPI obrazu tak, jak będzie on faktycznie
wydrukowany: rozmiar w pikselach podzielony przez rozmiar, w jakim obraz jest
narysowany na stronie (CTM w momencie operatora Do / BI). Metadane DPI z pliku
obrazu nie są używane – liczy się tylko to, jak duży obraz jest na stronie.

    python skills/pdf-check/scripts/pdf_images.py plik.pdf
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field

from pypdf.errors import PdfReadError
from pypdf.generic import ContentStream

from pdf_boxes import InvalidPdfError, open_pdf

PT_TO_MM = 25.4 / 72
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
MAX_DEPTH = 20


def mat_mult(m1: tuple, m2: tuple) -> tuple:
    """Złożenie macierzy PDF (konwencja wektorów wierszowych): najpierw m1, potem m2."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _apply(m: tuple, x: float, y: float) -> tuple:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def placed_size_pt(ctm: tuple) -> tuple:
    """Rozmiar jednostkowego kwadratu [0,1]×[0,1] po CTM, w punktach PDF (szer., wys.)."""
    ox, oy = _apply(ctm, 0, 0)
    xx, xy = _apply(ctm, 1, 0)
    yx, yy = _apply(ctm, 0, 1)
    return math.hypot(xx - ox, xy - oy), math.hypot(yx - ox, yy - oy)


@dataclass
class ImagePlacement:
    name: str
    px_w: int
    px_h: int
    placed_w_mm: float
    placed_h_mm: float

    @property
    def dpi_x(self) -> float:
        return self.px_w / (self.placed_w_mm / 25.4)

    @property
    def dpi_y(self) -> float:
        return self.px_h / (self.placed_h_mm / 25.4)

    @property
    def dpi(self) -> float:
        return (self.dpi_x + self.dpi_y) / 2


@dataclass
class PageImages:
    page: int                                       # numer strony od 1
    images: list = field(default_factory=list)      # list[ImagePlacement]

    @property
    def min_dpi(self):
        return min((im.dpi for im in self.images), default=None)


def _image_size(xobj) -> "tuple | None":
    w, h = xobj.get("/Width"), xobj.get("/Height")
    if not w or not h:
        return None
    return int(w), int(h)


def _record(acc: list, name: str, px_w: int, px_h: int, ctm: tuple) -> None:
    w_pt, h_pt = placed_size_pt(ctm)
    if w_pt <= 0 or h_pt <= 0 or px_w <= 0 or px_h <= 0:
        return  # macierz zdegenerowana (zerowa skala) albo zerowy obraz – DPI nieokreślone
    acc.append(ImagePlacement(name, px_w, px_h, w_pt * PT_TO_MM, h_pt * PT_TO_MM))


def _resource(resources, kind: str, name):
    if resources is None:
        return None
    group = resources.get_object().get(kind)
    if group is None:
        return None
    obj = group.get_object().get(str(name))
    return obj.get_object() if obj is not None else None


def _walk(stream, resources, pdf, acc: list, ctm: tuple, visiting: set, depth: int = 0) -> None:
    """Przechodzi operatory treści śledząc CTM; formularze (Form XObject) rekurencyjnie."""
    if depth > MAX_DEPTH:
        return
    ops = stream.operations if isinstance(stream, ContentStream) else ContentStream(stream, pdf).operations
    stack = []
    cur = ctm
    for operands, op in ops:
        if op == b"q":
            stack.append(cur)
        elif op == b"Q":
            if stack:
                cur = stack.pop()
        elif op == b"cm":
            m = tuple(float(x) for x in operands)
            cur = mat_mult(m, cur)
        elif op == b"INLINE IMAGE":
            settings = operands["settings"]
            if settings.get("/IM", settings.get("/ImageMask", False)):
                continue
            w, h = settings.get("/W", settings.get("/Width")), settings.get("/H", settings.get("/Height"))
            if w and h:
                _record(acc, "inline", int(w), int(h), cur)
        elif op == b"Do":
            _draw_xobject(operands[0], resources, pdf, acc, cur, visiting, depth)


def _draw_xobject(name, resources, pdf, acc: list, ctm: tuple, visiting: set, depth: int) -> None:
    group = resources.get_object().get("/XObject") if resources is not None else None
    group = group.get_object() if group is not None else None
    if group is None or str(name) not in group:
        return
    ref = group.raw_get(str(name))   # odwołanie pośrednie – jego numer chroni przed pętlą
    xobj = ref.get_object()
    subtype = xobj.get("/Subtype")
    if subtype == "/Image":
        if xobj.get("/ImageMask", False):
            return
        size = _image_size(xobj)
        if size is not None:
            _record(acc, str(name), size[0], size[1], ctm)
    elif subtype == "/Form":
        key = getattr(ref, "idnum", id(xobj))
        if key in visiting:          # formularz rysujący sam siebie
            return
        visiting.add(key)
        matrix = xobj.get("/Matrix")
        m = tuple(float(x) for x in matrix) if matrix else IDENTITY
        _walk(xobj, xobj.get("/Resources", resources), pdf, acc, mat_mult(m, ctm), visiting, depth + 1)
        visiting.discard(key)


def page_images(path) -> list:
    """Obrazy osadzone na każdej stronie PDF z ich efektywnym DPI. Zwraca list[PageImages]."""
    reader = open_pdf(path)
    pages = []
    try:
        for i, page in enumerate(reader.pages, start=1):
            acc: list = []
            contents = page.get_contents()
            if contents is not None:
                _walk(contents, page.get("/Resources"), reader, acc, IDENTITY, set())
            pages.append(PageImages(page=i, images=acc))
    except (PdfReadError, KeyError, IndexError, ValueError) as e:
        raise InvalidPdfError(f"Nie da się odczytać treści stron: {e}") from e
    return pages


def format_text(pages: list) -> str:
    lines = []
    for p in pages:
        if not p.images:
            lines.append(f"strona {p.page}: brak obrazów")
            continue
        parts = [f"{im.name} {im.px_w}×{im.px_h}px → {im.placed_w_mm:.0f}×{im.placed_h_mm:.0f}mm "
                 f"(ok. {im.dpi:.0f} dpi)" for im in p.images]
        lines.append(f"strona {p.page}: " + " | ".join(parts))
    return "\n".join(lines)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(format_text(page_images(arg)))
