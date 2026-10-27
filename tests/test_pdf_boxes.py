"""Testy read_boxes: happy path, błędne dane wejściowe, progi znaczników cięcia."""
import math
import sys
from pathlib import Path

import pytest
from conftest import NOT_A_PATH
from pypdf import PdfWriter
from pypdf.generic import RectangleObject

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "pdf-check" / "scripts"))

import pdf_boxes as B  # noqa: E402

MM_TO_PT = 72 / 25.4


def _rect(x0, y0, x1, y1):
    return RectangleObject([x0 * MM_TO_PT, y0 * MM_TO_PT, x1 * MM_TO_PT, y1 * MM_TO_PT])


def make_pdf(path: Path, pages: list) -> Path:
    """Buduje PDF z pustymi stronami o zadanych pudełkach (wszystko w mm).

    Każda strona: {"media": (w, h)} + opcjonalnie "trim"/"bleed" jako (x0, y0, x1, y1),
    "origin" (przesunięcie MediaBox) i "rotate".
    """
    w = PdfWriter()
    for spec in pages:
        mw, mh = spec["media"]
        page = w.add_blank_page(width=mw * MM_TO_PT, height=mh * MM_TO_PT)
        ox, oy = spec.get("origin", (0, 0))
        if ox or oy:
            page.mediabox = _rect(ox, oy, ox + mw, oy + mh)
        if "trim" in spec:
            page.trimbox = _rect(*spec["trim"])
        if "bleed" in spec:
            page.bleedbox = _rect(*spec["bleed"])
        if spec.get("rotate"):
            page.rotate(spec["rotate"])
    with open(path, "wb") as f:
        w.write(f)
    return path


def centered(media_w, media_h, w, h):
    """Prostokąt w × h wyśrodkowany na arkuszu media_w × media_h."""
    x0, y0 = (media_w - w) / 2, (media_h - h) / 2
    return (x0, y0, x0 + w, y0 + h)


def uniform_margin_pdf(tmp_path, margin_mm):
    """Wizytówka 90×50 + spad 2,5 mm, arkusz większy o `margin_mm` z każdej strony."""
    mw, mh = 95 + 2 * margin_mm, 55 + 2 * margin_mm
    return make_pdf(tmp_path / "m.pdf", [{
        "media": (mw, mh),
        "trim": centered(mw, mh, 90, 50),
        "bleed": centered(mw, mh, 95, 55),
    }])


# --- happy path: wizytówka z Canvy ze spadami i znacznikami cięcia ------------------

# Arkusz 110×70 mm, BleedBox 95×55, TrimBox 90×50 (znaczniki 7,5 mm z każdej strony)
CANVA_CARD = {
    "media": (110, 70),
    "trim": (10, 10, 100, 60),
    "bleed": (7.5, 7.5, 102.5, 62.5),
}


@pytest.fixture
def canva_card(tmp_path):
    return make_pdf(tmp_path / "wizytowka.pdf", [CANVA_CARD])


def test_read_boxes_happy_path(canva_card):
    pages = B.read_boxes(canva_card)
    assert isinstance(pages, list) and len(pages) == 1

    g = pages[0]
    assert isinstance(g, B.PageGeometry)
    assert g.page == 1
    assert g.rotation == 0
    assert g.trim_explicit is True and g.bleed_explicit is True

    # pudełka przeliczone z pt na mm, względem lewego dolnego rogu arkusza
    assert all(isinstance(b, B.Box) for b in (g.media, g.trim, g.bleed))
    assert (g.media.x0, g.media.y0, g.media.x1, g.media.y1) == pytest.approx((0, 0, 110, 70))
    assert (g.bleed.x0, g.bleed.y0, g.bleed.x1, g.bleed.y1) == pytest.approx((7.5, 7.5, 102.5, 62.5))
    assert (g.trim.x0, g.trim.y0, g.trim.x1, g.trim.y1) == pytest.approx((10, 10, 100, 60))

    assert g.trim_size == (90, 50)
    assert g.bleed_mm == {"left": 2.5, "right": 2.5, "top": 2.5, "bottom": 2.5}
    assert g.media_margin_mm == {"left": 7.5, "right": 7.5, "top": 7.5, "bottom": 7.5}
    assert g.has_crop_marks is True


def test_accepts_str_path(canva_card):
    assert B.read_boxes(str(canva_card))[0].trim_size == (90, 50)


def test_format_text(canva_card):
    text = B.format_text(B.read_boxes(canva_card))
    assert "netto 90.0 × 50.0 mm" in text
    assert "znaczniki cięcia: tak" in text


# Inne poprawne pliki.
def test_export_without_marks(tmp_path):
    """PDF ze spadami bez znaczników: MediaBox = BleedBox."""
    pdf = make_pdf(tmp_path / "a.pdf", [{
        "media": (95, 55), "trim": (2.5, 2.5, 92.5, 52.5), "bleed": (0, 0, 95, 55),
    }])
    g = B.read_boxes(pdf)[0]
    assert g.trim_size == (90, 50)
    assert g.bleed_mm["left"] == 2.5
    assert g.has_crop_marks is False


def test_no_boxes_falls_back_to_media(tmp_path):
    """Brak TrimBox i BleedBox: oba = MediaBox, flagi explicit = False."""
    g = B.read_boxes(make_pdf(tmp_path / "a.pdf", [{"media": (148, 210)}]))[0]
    assert g.trim_explicit is False and g.bleed_explicit is False
    assert g.trim_size == (148, 210)
    assert set(g.bleed_mm.values()) == {0}
    assert g.has_crop_marks is False


def test_trim_without_bleedbox(tmp_path):
    """Tylko TrimBox: BleedBox = MediaBox (spec PDF), więc spad liczony do arkusza."""
    pdf = make_pdf(tmp_path / "a.pdf", [{"media": (95, 55), "trim": (2.5, 2.5, 92.5, 52.5)}])
    g = B.read_boxes(pdf)[0]
    assert g.bleed_explicit is False
    assert g.bleed_mm == {"left": 2.5, "right": 2.5, "top": 2.5, "bottom": 2.5}
    assert g.has_crop_marks is False


@pytest.mark.parametrize("rotate,expected",
                         [
                             (0, (90, 50)),
                             (90, (50, 90)),
                             (180, (90, 50)),
                             (270, (50, 90)),
                             (-90, (50, 90))
                         ]
                         )
def test_rotation_swaps_trim_size(tmp_path, rotate, expected):
    pdf = make_pdf(tmp_path / "a.pdf", [dict(CANVA_CARD, rotate=rotate)])
    g = B.read_boxes(pdf)[0]
    assert g.rotation == rotate % 360
    assert g.trim_size == expected


def test_media_with_offset_origin(tmp_path):
    """MediaBox nie zaczyna się w (0,0) – wyniki mają być takie same."""
    pdf = make_pdf(tmp_path / "a.pdf", [{
        "media": (110, 70), "origin": (50, 30),
        "trim": (60, 40, 150, 90), "bleed": (57.5, 37.5, 152.5, 92.5),
    }])
    g = B.read_boxes(pdf)[0]
    assert (g.media.x0, g.media.y0) == pytest.approx((0, 0))
    assert g.trim_size == (90, 50)
    assert g.bleed_mm["left"] == 2.5
    assert g.media_margin_mm["left"] == 7.5


def test_multipage_mixed(tmp_path):
    """Okładka + środek: różne rozmiary stron, numeracja od 1."""
    pdf = make_pdf(tmp_path / "a.pdf", [
        CANVA_CARD,
        {"media": (215, 302), "trim": (2.5, 2.5, 212.5, 299.5), "bleed": (0, 0, 215, 302)},
        {"media": (148, 210)},
    ])
    pages = B.read_boxes(pdf)
    assert [g.page for g in pages] == [1, 2, 3]
    assert [g.trim_size for g in pages] == [(90, 50), (210, 297), (148, 210)]
    assert [g.has_crop_marks for g in pages] == [True, False, False]


def test_asymmetric_bleed(tmp_path):
    """Spad tylko z lewej (np. strona katalogu przy grzbiecie)."""
    pdf = make_pdf(tmp_path / "a.pdf", [{
        "media": (212.5, 297), "trim": (2.5, 0, 212.5, 297), "bleed": (0, 0, 212.5, 297),
    }])
    assert B.read_boxes(pdf)[0].bleed_mm == {"left": 2.5, "right": 0, "top": 0, "bottom": 0}


def test_empty_pdf_returns_empty_list(tmp_path):
    path = tmp_path / "pusty.pdf"
    with open(path, "wb") as f:
        PdfWriter().write(f)
    assert B.read_boxes(path) == []


# --- błędne dane wejściowe ---------------------------------------------------------

@pytest.mark.parametrize("bad", NOT_A_PATH)
def test_read_boxes_not_a_path(bad):
    with pytest.raises(TypeError):
        B.read_boxes(bad)


def test_read_boxes_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="Nie ma pliku"):
        B.read_boxes(tmp_path / "nie_ma.pdf")


def test_read_boxes_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        B.read_boxes(tmp_path / "brak_folderu" / "plik.pdf")


def test_read_boxes_directory_instead_of_file(tmp_path):
    with pytest.raises(IsADirectoryError):
        B.read_boxes(tmp_path)


def test_read_boxes_empty_string():
    # Path("") == "." – katalog bieżący, nie plik
    with pytest.raises(IsADirectoryError):
        B.read_boxes("")


@pytest.mark.parametrize("name", ["pusty", "jpg", "tekst", "html", "sam_naglowek"])
def test_read_boxes_not_a_pdf(not_pdf_files, name):
    with pytest.raises(B.InvalidPdfError):
        B.read_boxes(not_pdf_files[name])


def test_read_boxes_truncated_pdf(truncated_pdf):
    with pytest.raises(B.InvalidPdfError):
        B.read_boxes(truncated_pdf)


def test_read_boxes_password_protected(password_pdf):
    with pytest.raises(B.EncryptedPdfError, match="hasłem"):
        B.read_boxes(password_pdf)


def test_read_boxes_owner_locked_opens(owner_locked_pdf):
    """Blokada edycji to nie problem – plik da się przeczytać bez hasła."""
    assert len(B.read_boxes(owner_locked_pdf)) == 1


def test_invalid_pdf_errors_are_value_errors():
    assert issubclass(B.InvalidPdfError, ValueError)
    assert issubclass(B.EncryptedPdfError, B.InvalidPdfError)


# --- próg znaczników cięcia ---------------------------------------------------------

@pytest.mark.parametrize("margin,threshold,expected", [
    (7.5, 3.0, True),     # typowy eksport z Canvy
    (0, 3.0, False),      # brak nadmiaru arkusza
    (2.99, 3.0, False),   # tuż pod progiem
    (3.0, 3.0, False),    # dokładnie próg – porównanie ostre
    (3.01, 3.0, True),    # tuż nad progiem
    (7.5, 7.5, False),    # próg równy znacznikom
    (7.5, 7.49, True),
    (7.5, 20.0, False),   # bardzo wysoki próg
    (0, 0, False),        # próg 0, brak nadmiaru
    (0.01, 0, True),      # próg 0, najmniejszy mierzalny nadmiar
    (0.004, 0, False),    # szum poniżej precyzji 0,01 mm
])


def test_uniform_margin(tmp_path, margin, threshold, expected):
    pdf = uniform_margin_pdf(tmp_path, margin)
    g = B.read_boxes(pdf, marks_threshold_mm=threshold)[0]
    assert g.media_margin_mm["left"] == pytest.approx(round(margin, 2))
    assert g.has_crop_marks is expected


@pytest.mark.parametrize("margin", [1 / 3, 2 / 3, 25.4 / 72 * 7, 8.503937 * 25.4 / 72])
def test_float_noise_at_exact_threshold(tmp_path, margin):
    """Wartości, które w pt/mm nie są „okrągłe” – nadmiar = próg ma dać False."""
    pdf = uniform_margin_pdf(tmp_path, margin)
    threshold = round(margin, 2)
    assert B.read_boxes(pdf, marks_threshold_mm=threshold)[0].has_crop_marks is False


def test_one_side_only(tmp_path):
    """Znaczniki tylko z lewej – wystarczy jedna strona."""
    pdf = make_pdf(tmp_path / "a.pdf", [{
        "media": (105, 55), "trim": (12.5, 2.5, 102.5, 52.5), "bleed": (10, 0, 105, 55),
    }])
    g = B.read_boxes(pdf)[0]
    assert g.media_margin_mm == {"left": 10, "right": 0, "top": 0, "bottom": 0}
    assert g.has_crop_marks is True


def test_per_side_not_total(tmp_path):
    """2 mm z każdej strony = 4 mm łącznie, ale żadna strona nie przekracza 3 mm."""
    pdf = uniform_margin_pdf(tmp_path, 2.0)
    assert B.read_boxes(pdf, marks_threshold_mm=3.0)[0].has_crop_marks is False


def test_bleed_mistaken_for_marks_is_avoided(tmp_path):
    """Brak BleedBox, arkusz = netto + 2,5 mm: domyślny próg nie bierze spadu za znaczniki."""
    pdf = make_pdf(tmp_path / "a.pdf", [{"media": (95, 55), "trim": (2.5, 2.5, 92.5, 52.5)}])
    assert B.read_boxes(pdf)[0].has_crop_marks is False


def test_threshold_applies_to_each_page(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [
        {"media": (99, 59), "trim": centered(99, 59, 90, 50), "bleed": centered(99, 59, 95, 55)},
        CANVA_CARD,
    ])
    assert [g.has_crop_marks for g in B.read_boxes(pdf, marks_threshold_mm=3)] == [False, True]
    assert [g.has_crop_marks for g in B.read_boxes(pdf, marks_threshold_mm=1)] == [True, True]


def test_int_threshold_accepted(canva_card):
    assert B.read_boxes(canva_card, marks_threshold_mm=3)[0].has_crop_marks is True


@pytest.mark.parametrize("bad", [-0.01, -3, math.nan, math.inf, -math.inf])
def test_invalid_threshold_value(canva_card, bad):
    with pytest.raises(ValueError):
        B.read_boxes(canva_card, marks_threshold_mm=bad)


@pytest.mark.parametrize("bad", ["3", None, True, [3]])
def test_invalid_threshold_type(canva_card, bad):
    with pytest.raises(TypeError):
        B.read_boxes(canva_card, marks_threshold_mm=bad)


def test_threshold_validated_before_opening_file(tmp_path):
    """Zły próg zgłoszony nawet przy złej ścieżce – błąd wywołania, nie pliku."""
    with pytest.raises(ValueError):
        B.read_boxes(tmp_path / "nie_ma.pdf", marks_threshold_mm=-1)
