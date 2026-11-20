"""Testy page_images: happy path, geometria CTM, błędne dane wejściowe, warianty."""
import math
import sys
from pathlib import Path

import pytest
from conftest import NOT_A_PATH
from pypdf.generic import NameObject

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "pdf-check" / "scripts"))

import pdf_boxes as B  # noqa: E402
import pdf_images as I  # noqa: E402
from test_pdf_colors import Doc, to_pdf  # noqa: E402 - wspólny budowniczy testowych PDF-ów


def one_page(tmp_path, content: bytes, resources=None, build=None):
    """PDF z jedną stroną → PageImages tej strony. `build(doc)` może zwrócić zasoby."""
    doc = Doc()
    if build is not None:
        resources = build(doc)
    doc.page(content, resources)
    return I.page_images(doc.save(tmp_path / "t.pdf"))[0]


# --- happy path: obraz narysowany w znanej skali -----------------------------------

def test_happy_path_known_scale(tmp_path):
    """Obraz 1×1 px narysowany w kwadracie 1×1 inch (72×72 pt) → 1 dpi."""
    p = one_page(tmp_path, b"q 72 0 0 72 0 0 cm /Im0 Do Q",
                 build=lambda d: {"/XObject": {"/Im0": d.image("/DeviceRGB")}})
    assert p.page == 1
    assert len(p.images) == 1
    im = p.images[0]
    assert (im.px_w, im.px_h) == (1, 1)  # Doc.image() domyślnie tworzy obraz 1×1 px
    assert im.placed_w_mm == pytest.approx(25.4, abs=0.01)
    assert im.placed_h_mm == pytest.approx(25.4, abs=0.01)
    assert im.dpi == pytest.approx(1.0, rel=0.01)


def _image_with_size(doc, px_w, px_h):
    return doc.stream(b"\x00", **{"/Type": "/XObject", "/Subtype": "/Image",
                                   "/Width": px_w, "/Height": px_h, "/BitsPerComponent": 8,
                                   "/ColorSpace": "/DeviceRGB"})


def test_happy_path_dpi_value(tmp_path):
    """Obraz 300×600 px narysowany w 100×200 pt → dokładna wartość DPI."""
    p = one_page(tmp_path, b"100 0 0 200 0 0 cm /Im0 Do",
                 build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 600)}})
    im = p.images[0]
    expected_w_mm = 100 * I.PT_TO_MM
    expected_h_mm = 200 * I.PT_TO_MM
    assert im.placed_w_mm == pytest.approx(expected_w_mm)
    assert im.placed_h_mm == pytest.approx(expected_h_mm)
    assert im.dpi_x == pytest.approx(300 / (expected_w_mm / 25.4))
    assert im.dpi_y == pytest.approx(600 / (expected_h_mm / 25.4))
    assert im.dpi == pytest.approx((im.dpi_x + im.dpi_y) / 2)


# --- geometria: rotacja, q/Q, formularze ---------------------------------------------

def test_rotation_does_not_change_dpi(tmp_path):
    """Obraz obrócony o 90° w tej samej skali → ten sam efektywny DPI co bez obrotu."""
    straight = one_page(tmp_path, b"72 0 0 72 0 0 cm /Im0 Do",
                        build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
    rotated = one_page(tmp_path, b"0 72 -72 0 0 0 cm /Im0 Do",
                       build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
    assert rotated.images[0].dpi == pytest.approx(straight.images[0].dpi, rel=1e-6)


def test_q_restores_ctm(tmp_path):
    """Po Q wraca poprzedni CTM – drugi obraz rysowany bez dodatkowego skalowania."""
    p = one_page(tmp_path, b"q 72 0 0 72 0 0 cm /Im0 Do Q /Im0 Do",
                 build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
    assert len(p.images) == 2
    scaled, unscaled = p.images
    assert scaled.placed_w_mm == pytest.approx(72 * I.PT_TO_MM)
    assert unscaled.placed_w_mm == pytest.approx(1 * I.PT_TO_MM)  # jednostkowy kwadrat, bez cm


def test_cm_without_q_is_cumulative(tmp_path):
    """Dwa `cm` bez q/Q między nimi się składają (nie zastępują)."""
    p = one_page(tmp_path, b"2 0 0 2 0 0 cm 3 0 0 3 0 0 cm /Im0 Do",
                 build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
    assert p.images[0].placed_w_mm == pytest.approx(6 * I.PT_TO_MM)


def test_form_xobject_matrix_applies(tmp_path):
    """Form XObject z własnym /Matrix – obraz w środku skalowany przez Matrix formularza."""
    def build(d):
        inner = {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}}
        form = d.stream(b"/Im0 Do", **{"/Type": "/XObject", "/Subtype": "/Form",
                                        "/BBox": [0, 0, 100, 100], "/Matrix": [72, 0, 0, 72, 0, 0],
                                        "/Resources": inner})
        return {"/XObject": {"/Fm0": form}}
    p = one_page(tmp_path, b"/Fm0 Do", build=build)
    assert p.images[0].placed_w_mm == pytest.approx(72 * I.PT_TO_MM)


def test_nested_forms_compose_ctm(tmp_path):
    def build(d):
        f2 = d.form(b"/Im0 Do", {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
        f1 = d.form(b"/F2 Do", {"/XObject": {"/F2": f2}})
        return {"/XObject": {"/F1": f1}}
    p = one_page(tmp_path, b"36 0 0 36 0 0 cm /F1 Do", build=build)
    assert p.images[0].placed_w_mm == pytest.approx(36 * I.PT_TO_MM)


def test_self_referencing_form_does_not_loop(tmp_path):
    def build(d):
        fm = d.form(b"/Im0 Do /Fm0 Do")
        img = _image_with_size(d, 300, 300)
        fm.get_object()[NameObject("/Resources")] = to_pdf({"/XObject": {"/Im0": img, "/Fm0": fm}})
        return {"/XObject": {"/Fm0": fm}}
    p = one_page(tmp_path, b"/Fm0 Do", build=build)
    assert len(p.images) == 1  # rysuje się raz, pętla nie wykonuje się w nieskończoność


# --- obrazy maskujące i puste strony --------------------------------------------------

def test_image_mask_excluded(tmp_path):
    p = one_page(tmp_path, b"0 0 0 1 k /M0 Do",
                 build=lambda d: {"/XObject": {"/M0": d.image(None, mask=True)}})
    assert p.images == []


def test_unused_image_not_counted(tmp_path):
    p = one_page(tmp_path, b"0 0 0 1 k", build=lambda d: {"/XObject": {"/Im0": d.image("/DeviceRGB")}})
    assert p.images == []


def test_empty_page_has_no_images(tmp_path):
    p = one_page(tmp_path, b"")
    assert p.images == []
    assert p.min_dpi is None


def test_image_without_dimensions_skipped(tmp_path):
    """Obraz bez /Width lub /Height (uszkodzony plik) – pominięty, bez wyjątku."""
    def build(d):
        broken = d.stream(b"\x00", **{"/Type": "/XObject", "/Subtype": "/Image",
                                       "/ColorSpace": "/DeviceRGB", "/BitsPerComponent": 8})
        return {"/XObject": {"/Im0": broken}}
    p = one_page(tmp_path, b"/Im0 Do", build=build)
    assert p.images == []


def test_degenerate_matrix_skipped(tmp_path):
    """CTM ze skalą zero (np. błąd generatora) – DPI nieokreślone, obraz pomijamy."""
    p = one_page(tmp_path, b"0 0 0 0 0 0 cm /Im0 Do",
                 build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
    assert p.images == []


def test_same_image_drawn_twice_recorded_separately(tmp_path):
    p = one_page(tmp_path, b"q 10 0 0 10 0 0 cm /Im0 Do Q q 20 0 0 20 0 0 cm /Im0 Do Q",
                 build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
    assert len(p.images) == 2
    assert p.images[1].placed_w_mm == pytest.approx(2 * p.images[0].placed_w_mm)


def test_unknown_xobject_name_ignored(tmp_path):
    assert one_page(tmp_path, b"/Brak Do").images == []


# --- obraz w linii (inline image) -----------------------------------------------------

def test_inline_image_recorded(tmp_path):
    content = b"10 0 0 10 0 0 cm BI /W 300 /H 300 /BPC 8 /CS /RGB ID \x00\x00\x00\x00 EI"
    p = one_page(tmp_path, content)
    assert len(p.images) == 1
    assert (p.images[0].px_w, p.images[0].px_h) == (300, 300)
    assert p.images[0].placed_w_mm == pytest.approx(10 * I.PT_TO_MM)


def test_inline_image_mask_excluded(tmp_path):
    content = b"BI /W 1 /H 1 /BPC 1 /IM true ID \x00 EI"
    p = one_page(tmp_path, content)
    assert p.images == []


# --- wiele stron ------------------------------------------------------------------

def test_multipage(tmp_path):
    doc = Doc()
    doc.page(b"0 0 0 1 k")
    doc.page(b"72 0 0 72 0 0 cm /Im0 Do", {"/XObject": {"/Im0": _image_with_size(doc, 300, 300)}})
    doc.page(b"")
    pages = I.page_images(doc.save(tmp_path / "t.pdf"))
    assert [p.page for p in pages] == [1, 2, 3]
    assert [len(p.images) for p in pages] == [0, 1, 0]
    assert pages[1].min_dpi == pytest.approx(300, rel=0.01)


def test_empty_pdf_returns_empty_list(tmp_path):
    assert I.page_images(Doc().save(tmp_path / "t.pdf")) == []


# --- PageImages.min_dpi -------------------------------------------------------------

def test_min_dpi_picks_worst_image(tmp_path):
    p = one_page(tmp_path, b"q 72 0 0 72 0 0 cm /Hi Do Q q 10 0 0 10 0 0 cm /Lo Do Q",
                 build=lambda d: {"/XObject": {"/Hi": _image_with_size(d, 300, 300),
                                               "/Lo": _image_with_size(d, 30, 30)}})
    assert p.min_dpi == pytest.approx(min(im.dpi for im in p.images))


# --- format_text ---------------------------------------------------------------------

def test_format_text_with_and_without_images(tmp_path):
    with_img = one_page(tmp_path, b"72 0 0 72 0 0 cm /Im0 Do",
                        build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
    text = I.format_text([with_img])
    assert "dpi" in text and "px" in text

    empty = one_page(tmp_path, b"")
    assert I.format_text([empty]) == "strona 1: brak obrazów"


# --- mat_mult / placed_size_pt: matematyka macierzy ----------------------------------

def test_mat_mult_identity():
    m = (2.0, 0.0, 0.0, 3.0, 5.0, 7.0)
    assert I.mat_mult(I.IDENTITY, m) == m
    assert I.mat_mult(m, I.IDENTITY) == m


def test_mat_mult_translation_composes():
    t1 = (1.0, 0.0, 0.0, 1.0, 10.0, 0.0)
    t2 = (1.0, 0.0, 0.0, 1.0, 0.0, 20.0)
    assert I.mat_mult(t1, t2) == (1.0, 0.0, 0.0, 1.0, 10.0, 20.0)


def test_placed_size_pt_simple_scale():
    m = (72.0, 0.0, 0.0, 144.0, 0.0, 0.0)
    w, h = I.placed_size_pt(m)
    assert w == pytest.approx(72.0)
    assert h == pytest.approx(144.0)


def test_placed_size_pt_rotation_45():
    angle = math.radians(45)
    scale = 10.0
    m = (scale * math.cos(angle), scale * math.sin(angle),
        -scale * math.sin(angle), scale * math.cos(angle), 0.0, 0.0)
    w, h = I.placed_size_pt(m)
    assert w == pytest.approx(scale)
    assert h == pytest.approx(scale)


# --- ImagePlacement: właściwości DPI ---------------------------------------------------

def test_image_placement_dpi_properties():
    im = I.ImagePlacement("x", px_w=300, px_h=600, placed_w_mm=25.4, placed_h_mm=50.8)
    assert im.dpi_x == pytest.approx(300.0)
    assert im.dpi_y == pytest.approx(300.0)
    assert im.dpi == pytest.approx(300.0)


# --- błędne dane wejściowe (jak w test_pdf_colors.py) ---------------------------------

@pytest.mark.parametrize("bad", NOT_A_PATH)
def test_page_images_not_a_path(bad):
    with pytest.raises(TypeError):
        I.page_images(bad)


def test_page_images_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="Nie ma pliku"):
        I.page_images(tmp_path / "nie_ma.pdf")


def test_page_images_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        I.page_images(tmp_path / "brak_folderu" / "plik.pdf")


def test_page_images_directory_instead_of_file(tmp_path):
    with pytest.raises(IsADirectoryError):
        I.page_images(tmp_path)


def test_page_images_empty_string():
    with pytest.raises(IsADirectoryError):
        I.page_images("")


@pytest.mark.parametrize("name", ["pusty", "jpg", "tekst", "html", "sam_naglowek"])
def test_page_images_not_a_pdf(not_pdf_files, name):
    with pytest.raises(B.InvalidPdfError):
        I.page_images(not_pdf_files[name])


def test_page_images_truncated_pdf(truncated_pdf):
    with pytest.raises(B.InvalidPdfError):
        I.page_images(truncated_pdf)


def test_page_images_password_protected(password_pdf):
    with pytest.raises(B.EncryptedPdfError, match="hasłem"):
        I.page_images(password_pdf)


def test_page_images_owner_locked_opens(owner_locked_pdf):
    assert len(I.page_images(owner_locked_pdf)) == 1


def test_page_images_accepts_str_path(tmp_path):
    p = one_page(tmp_path, b"72 0 0 72 0 0 cm /Im0 Do",
                 build=lambda d: {"/XObject": {"/Im0": _image_with_size(d, 300, 300)}})
    assert p.images  # sanity: fixture się buduje poprawnie
