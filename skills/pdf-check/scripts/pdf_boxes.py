"""Geometria stron PDF: MediaBox / TrimBox / BleedBox, format netto, spady, znaczniki cięcia.

Moduł tylko mierzy – nie ocenia. Werdykty (BŁĄD / OSTRZEŻENIE) powstają dalej,
po porównaniu z produktem z rules.yaml.

    python skills/pdf-check/scripts/pdf_boxes.py plik.pdf
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PyPdfError

PT_TO_MM = 25.4 / 72
# Pomiary zaokrąglamy do 0,01 mm – PDF zapisuje liczby z ograniczoną precyzją,
# więc 3 mm potrafi wrócić jako 3,0000004 mm i fałszywie przekroczyć próg.
PRECISION = 2


class InvalidPdfError(ValueError):
    """Plik istnieje, ale nie da się go odczytać jako PDF."""


class EncryptedPdfError(InvalidPdfError):
    """PDF zabezpieczony hasłem do otwarcia."""


@dataclass
class Box:
    """Prostokąt w mm, względem lewego dolnego rogu MediaBox."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class PageGeometry:
    page: int                # numer strony od 1
    media: Box
    trim: Box
    bleed: Box
    trim_explicit: bool      # czy TrimBox był w pliku (inaczej = CropBox/MediaBox)
    bleed_explicit: bool
    rotation: int            # 0 / 90 / 180 / 270
    bleed_mm: dict           # spad z każdej strony: BleedBox − TrimBox
    media_margin_mm: dict    # nadmiar arkusza z każdej strony: MediaBox − BleedBox
    has_crop_marks: bool     # któryś nadmiar arkusza większy niż próg

    @property
    def trim_size(self) -> tuple:
        """Format netto (szerokość, wysokość) w mm, tak jak widać go po obrocie."""
        w, h = round(self.trim.width, PRECISION), round(self.trim.height, PRECISION)
        return (h, w) if self.rotation in (90, 270) else (w, h)


def to_box(pdf_box, origin: tuple) -> Box:
    """Prostokąt pypdf (pt, współrzędne PDF) → Box w mm względem `origin`."""
    ox, oy = origin
    return Box(
        (float(pdf_box.left) - ox) * PT_TO_MM,
        (float(pdf_box.bottom) - oy) * PT_TO_MM,
        (float(pdf_box.right) - ox) * PT_TO_MM,
        (float(pdf_box.top) - oy) * PT_TO_MM,
    )


def side_gaps(inner: Box, outer: Box) -> dict:
    """Odległość od `inner` do `outer` z każdej strony, w mm (0,01 mm)."""
    return {
        "left": round(inner.x0 - outer.x0, PRECISION),
        "right": round(outer.x1 - inner.x1, PRECISION),
        "top": round(outer.y1 - inner.y1, PRECISION),
        "bottom": round(inner.y0 - outer.y0, PRECISION),
    }


def crop_marks_present(media_margin_mm: dict, threshold_mm: float) -> bool:
    """Znaczniki cięcia = arkusz wystaje poza BleedBox o więcej niż próg z którejś strony.

    Porównanie ostre: nadmiar równy progowi to jeszcze nie znaczniki.
    """
    return any(gap > threshold_mm for gap in media_margin_mm.values())


def _validate_threshold(threshold_mm) -> float:
    if isinstance(threshold_mm, bool) or not isinstance(threshold_mm, (int, float)):
        raise TypeError(f"marks_threshold_mm musi być liczbą, jest: {threshold_mm!r}")
    if math.isnan(threshold_mm) or math.isinf(threshold_mm) or threshold_mm < 0:
        raise ValueError(f"marks_threshold_mm musi być skończony i ≥ 0, jest: {threshold_mm}")
    return float(threshold_mm)


def open_pdf(path) -> PdfReader:
    """Otwiera PDF z czytelnym błędem dla złego argumentu, złej ścieżki lub złego pliku."""
    if not isinstance(path, (str, os.PathLike)):
        raise TypeError(f"Ścieżka do PDF musi być str lub Path, jest: {type(path).__name__}")
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Nie ma pliku: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"To nie jest plik: {path}")
    try:
        reader = PdfReader(path)
    except (PyPdfError, OSError, ValueError) as e:
        raise InvalidPdfError(f"Nie da się odczytać PDF {path.name}: {e}") from e
    # Plik z samym hasłem właściciela (blokada edycji) otwiera się pustym hasłem.
    if reader.is_encrypted:
        try:
            opened = reader.decrypt("")
        except PyPdfError:
            opened = 0
        if not opened:
            raise EncryptedPdfError(f"PDF {path.name} jest zabezpieczony hasłem – poprosić klienta o plik bez hasła")
    return reader


def page_geometry(page, number: int, threshold_mm: float) -> PageGeometry:
    """Geometria jednej strony (obiekt strony pypdf)."""
    # Obecność sprawdzamy PRZED odczytem: getter pypdf (page.trimbox) wpisuje
    # wartość domyślną do słownika strony, więc po odczycie pole „zawsze jest”.
    trim_explicit = "/TrimBox" in page
    bleed_explicit = "/BleedBox" in page
    origin = (float(page.mediabox.left), float(page.mediabox.bottom))
    media = to_box(page.mediabox, origin)
    # Zgodnie ze specyfikacją PDF brakujący BleedBox/TrimBox = CropBox = MediaBox.
    trim = to_box(page.trimbox, origin)
    bleed = to_box(page.bleedbox, origin)
    media_margin = side_gaps(bleed, media)
    return PageGeometry(
        page=number,
        media=media,
        trim=trim,
        bleed=bleed,
        trim_explicit=trim_explicit,
        bleed_explicit=bleed_explicit,
        rotation=page.rotation % 360,
        bleed_mm=side_gaps(trim, bleed),
        media_margin_mm=media_margin,
        has_crop_marks=crop_marks_present(media_margin, threshold_mm),
    )


def read_boxes(path, marks_threshold_mm: float = 3.0) -> list:
    """Geometria wszystkich stron PDF. Zwraca list[PageGeometry]."""
    threshold = _validate_threshold(marks_threshold_mm)
    reader = open_pdf(path)
    try:
        return [page_geometry(p, i, threshold) for i, p in enumerate(reader.pages, start=1)]
    except PdfReadError as e:
        raise InvalidPdfError(f"Uszkodzona struktura stron w {Path(path).name}: {e}") from e


def format_text(pages: list) -> str:
    lines = []
    for g in pages:
        w, h = g.trim_size
        b = g.bleed_mm
        lines.append(
            f"strona {g.page}: netto {w} × {h} mm | spad L/P/G/D "
            f"{b['left']}/{b['right']}/{b['top']}/{b['bottom']} | "
            f"znaczniki cięcia: {'tak' if g.has_crop_marks else 'nie'}"
        )
        lines.append(
            f"        MediaBox {round(g.media.width, PRECISION)} × {round(g.media.height, PRECISION)}"
            f" | TrimBox: {'jest' if g.trim_explicit else 'brak'}"
            f" | BleedBox: {'jest' if g.bleed_explicit else 'brak'}"
            f"{f' | obrót {g.rotation}°' if g.rotation else ''}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(format_text(read_boxes(arg)))
