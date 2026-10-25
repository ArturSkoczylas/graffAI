"""Przestrzenie barw użyte na stronach PDF: RGB / CMYK / Gray / kolory dodatkowe (spot).

Moduł tylko mierzy – nie ocenia. Liczymy to, co faktycznie jest rysowane (operatory
w treści strony), a nie wszystko, co leży w zasobach – Canva i inne programy potrafią
zostawić w zasobach nieużywane obrazy.

    python skills/pdf-check/scripts/pdf_colors.py plik.pdf
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field

from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, ContentStream

from pdf_boxes import InvalidPdfError, open_pdf

PROCESS_COLORANTS = {"Cyan", "Magenta", "Yellow", "Black"}
# Skróty z obrazów osadzonych w treści (BI … ID … EI)
INLINE_ABBREVIATIONS = {"/G": "/DeviceGray", "/RGB": "/DeviceRGB", "/CMYK": "/DeviceCMYK", "/I": "/Indexed"}
DEVICE_SPACES = {
    "/DeviceRGB": "RGB", "/CalRGB": "RGB",
    "/DeviceCMYK": "CMYK",
    "/DeviceGray": "Gray", "/CalGray": "Gray",
    "/Lab": "Lab",
    "/Pattern": "Pattern",
}
ICC_COMPONENTS = {1: "Gray", 3: "RGB", 4: "CMYK"}
OPERATOR_SPACES = {b"rg": "RGB", b"RG": "RGB", b"k": "CMYK", b"K": "CMYK", b"g": "Gray", b"G": "Gray"}
# Kategorie, które nie są kolorem farby: „All” = kolor rejestracyjny (znaczniki cięcia),
# „None” = nic nie drukuj.
REGISTRATION, NOTHING = "Registration", "None"
MAX_DEPTH = 20


@dataclass
class PageColors:
    page: int                                            # numer strony od 1
    images: Counter = field(default_factory=Counter)    # kategoria → ile razy narysowano obraz
    vector: set = field(default_factory=set)            # kategorie wypełnień, konturów, tekstu, cieniowań
    spot_names: set = field(default_factory=set)        # nazwy kolorów dodatkowych, np. {"Gold"}

    @property
    def has_rgb(self) -> bool:
        return "RGB" in self.images or "RGB" in self.vector


def classify(cs, resources, depth: int = 0) -> tuple:
    """Przestrzeń barw PDF → (kategoria, zbiór nazw spotów)."""
    if cs is None or depth > MAX_DEPTH:
        return "Unknown", set()
    cs = cs.get_object()

    if isinstance(cs, ArrayObject):
        if not cs:
            return "Unknown", set()
        family = str(cs[0])
        if family == "/ICCBased":
            n = int(cs[1].get_object().get("/N", 0))
            return ICC_COMPONENTS.get(n, "Unknown"), set()
        if family in ("/Indexed", "/I"):
            return classify(cs[1], resources, depth + 1)
        if family == "/Separation":
            return _colorants([str(cs[1])[1:]])
        if family == "/DeviceN":
            return _colorants([str(n)[1:] for n in cs[1].get_object()])
        if family == "/Pattern" and len(cs) > 1:
            return classify(cs[1], resources, depth + 1)
        return DEVICE_SPACES.get(family, "Unknown"), set()

    name = INLINE_ABBREVIATIONS.get(str(cs), str(cs))
    if name in DEVICE_SPACES:
        return DEVICE_SPACES[name], set()
    named = _resource(resources, "/ColorSpace", name)
    if named is not None:
        return classify(named, resources, depth + 1)
    return "Unknown", set()


def _colorants(names: list) -> tuple:
    """Barwniki z Separation / DeviceN → kategoria."""
    spots = {n for n in names if n not in PROCESS_COLORANTS | {"All", "None"}}
    if spots:
        return "Spot", spots
    if "All" in names:
        return REGISTRATION, set()
    if set(names) == {"None"}:
        return NOTHING, set()
    return "CMYK", set()


def _resource(resources, kind: str, name):
    if resources is None:
        return None
    group = resources.get_object().get(kind)
    if group is None:
        return None
    obj = group.get_object().get(str(name))
    return obj.get_object() if obj is not None else None


def _add(acc: PageColors, target: str, cs, resources):
    category, spots = classify(cs, resources)
    if category == NOTHING:
        return
    acc.spot_names |= spots
    if target == "image":
        acc.images[category] += 1
    else:
        acc.vector.add(category)


def _walk(stream, resources, pdf, acc: PageColors, visiting: set, depth: int = 0):
    """Przechodzi operatory treści; formularze (Form XObject) rekurencyjnie."""
    if depth > MAX_DEPTH:
        return
    ops = stream.operations if isinstance(stream, ContentStream) else ContentStream(stream, pdf).operations
    for operands, op in ops:
        if op in OPERATOR_SPACES:
            acc.vector.add(OPERATOR_SPACES[op])
        elif op in (b"cs", b"CS"):
            _add(acc, "vector", operands[0], resources)
        elif op == b"sh":
            shading = _resource(resources, "/Shading", operands[0])
            if shading is not None:
                _add(acc, "vector", shading.get("/ColorSpace"), resources)
        elif op == b"INLINE IMAGE":
            settings = operands["settings"]
            if not settings.get("/IM", settings.get("/ImageMask", False)):
                _add(acc, "image", settings.get("/CS", settings.get("/ColorSpace")), resources)
        elif op == b"Do":
            _draw_xobject(operands[0], resources, pdf, acc, visiting, depth)


def _draw_xobject(name, resources, pdf, acc, visiting, depth):
    group = resources.get_object().get("/XObject") if resources is not None else None
    group = group.get_object() if group is not None else None
    if group is None or str(name) not in group:
        return
    ref = group.raw_get(str(name))   # odwołanie pośrednie – jego numer chroni przed pętlą
    xobj = ref.get_object()
    subtype = xobj.get("/Subtype")
    if subtype == "/Image":
        # Maska obrazu maluje bieżącym kolorem wypełnienia – ten już policzyliśmy.
        if not xobj.get("/ImageMask", False):
            _add(acc, "image", xobj.get("/ColorSpace"), resources)
    elif subtype == "/Form":
        key = getattr(ref, "idnum", id(xobj))
        if key in visiting:          # formularz rysujący sam siebie
            return
        visiting.add(key)
        _walk(xobj, xobj.get("/Resources", resources), pdf, acc, visiting, depth + 1)
        visiting.discard(key)


def color_spaces(path) -> list:
    """Przestrzenie barw każdej strony PDF. Zwraca list[PageColors]."""
    reader = open_pdf(path)
    pages = []
    try:
        for i, page in enumerate(reader.pages, start=1):
            acc = PageColors(page=i)
            contents = page.get_contents()
            if contents is not None:
                _walk(contents, page.get("/Resources"), reader, acc, set())
            pages.append(acc)
    except (PdfReadError, KeyError, IndexError, ValueError) as e:
        raise InvalidPdfError(f"Nie da się odczytać treści stron: {e}") from e
    return pages


def format_text(pages: list) -> str:
    lines = []
    for p in pages:
        images = ", ".join(f"{k}×{v}" for k, v in sorted(p.images.items())) or "brak"
        vector = ", ".join(sorted(p.vector)) or "brak"
        spots = f" | spot: {', '.join(sorted(p.spot_names))}" if p.spot_names else ""
        lines.append(f"strona {p.page}: obrazy {images} | wektor/tekst {vector}{spots}"
                     f"{' | RGB!' if p.has_rgb else ''}")
    return "\n".join(lines)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(format_text(color_spaces(arg)))
