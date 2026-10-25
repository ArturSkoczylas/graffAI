"""Testy check_margins: happy path, błędne dane wejściowe, warianty spadów i marginesów."""
import math
import sys
from pathlib import Path

import pytest
from conftest import NOT_A_PATH
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, RectangleObject

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "pdf-check" / "scripts"))

import pdf_boxes as B  # noqa: E402
import pdf_margins as PM  # noqa: E402
from pdf_margins import M  # noqa: E402

MM_TO_PT = 72 / 25.4
BLUE = b"0.2 0.4 0.8 rg"
WHITE = b"1 1 1 rg"

# Ulotka A5 148×210 ze spadem 2,5 mm: arkusz 153×215, netto od 2,5 do 150,5 / 212,5
A5_TRIM = (2.5, 2.5, 150.5, 212.5)
A5_BLEED = (0, 0, 153, 215)


# --- budowanie PDF-ów testowych (wszystko w mm, początek w lewym dolnym rogu arkusza) ---

def rect(x0, y0, x1, y1, color=b"0 0 0 rg") -> bytes:
    return color + b" %f %f %f %f re f " % (x0, y0, x1 - x0, y1 - y0)


def frame(x0, y0, x1, y1, width=0.5) -> bytes:
    return b"0 0 0 RG %f w %f %f %f %f re S " % (width, x0, y0, x1 - x0, y1 - y0)


# „Tekst” to prawdziwy tekst (Helvetica) – silnik szuka gęstości krawędzi liter,
# zwykły prostokąt ma ich za mało i nie udaje tekstu.
# Linia jak stopka ulotki: 18 cyfr (0,556 em) + 5 spacji (0,278 em), wysokość cyfr ok. 0,71 em.
TEXT = b"660 361 988 660 361 988"
TEXT_SIZE = 3.5     # mm (ok. 10 pt)
TEXT_W = (18 * 0.556 + 5 * 0.278) * TEXT_SIZE
TEXT_H = 0.71 * TEXT_SIZE


def text(x, y, color=WHITE) -> bytes:
    """Tekst od (x, y): lewy brzeg pierwszej litery i linia bazowa, w mm."""
    return color + b" BT /F1 %f Tf %f %f Td (%s) Tj ET " % (TEXT_SIZE, x, y, TEXT)


def background(w=153, h=215) -> bytes:
    return rect(0, 0, w, h, BLUE)


def page_spec(media, trim=None, bleed=None, content=b"", rotate=0) -> dict:
    return {"media": media, "trim": trim, "bleed": bleed, "content": content, "rotate": rotate}


def make_pdf(path: Path, pages: list) -> Path:
    w = PdfWriter()
    for spec in pages:
        mw, mh = spec["media"]
        page = w.add_blank_page(width=mw * MM_TO_PT, height=mh * MM_TO_PT)
        if spec["trim"]:
            page.trimbox = RectangleObject([v * MM_TO_PT for v in spec["trim"]])
        if spec["bleed"]:
            page.bleedbox = RectangleObject([v * MM_TO_PT for v in spec["bleed"]])
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"%f 0 0 %f 0 0 cm " % (MM_TO_PT, MM_TO_PT) + spec["content"])
        page[NameObject("/Contents")] = w._add_object(stream)
        if spec["rotate"]:
            page.rotate(spec["rotate"])
    with open(path, "wb") as f:
        w.write(f)
    return path


def a5_pdf(tmp_path, content: bytes, name="a5.pdf") -> Path:
    """Ulotka A5 ze spadami i TrimBox/BleedBox."""
    return make_pdf(tmp_path / name, [page_spec((153, 215), A5_TRIM, A5_BLEED, content)])


def check_one(path, product="ulotka_a5", **kw) -> PM.PageMargins:
    pages = PM.check_margins(path, product, **kw)
    assert len(pages) == 1
    return pages[0]


# --- happy path: ulotka A5 z pełnym tłem w spadzie i tekstem daleko od krawędzi ------

@pytest.fixture
def good_a5(tmp_path):
    return a5_pdf(tmp_path, background() + text(30, 100), "dobra.pdf")


def test_check_margins_happy_path(good_a5):
    pages = PM.check_margins(good_a5, "ulotka_a5")
    assert isinstance(pages, list) and len(pages) == 1

    p = pages[0]
    assert isinstance(p, PM.PageMargins)
    assert p.page == 1
    assert p.trim_size == (148, 210)
    assert p.bleed_mm == {"left": 2.5, "right": 2.5, "top": 2.5, "bottom": 2.5}
    assert p.analysed_bleed_mm == 2.5
    assert p.render_dpi == PM.DEFAULT_RENDER_DPI
    assert p.status == "OK"
    assert p.findings == []
    assert p.codes == set()
    assert p.preview is None


def test_check_margins_accepts_product_object_and_str_path(good_a5):
    product = M.get_product(M.load_rules(), "ulotka_a5")
    assert check_one(str(good_a5), product).status == "OK"


def test_check_margins_preview(good_a5, tmp_path):
    p = check_one(good_a5, preview_dir=tmp_path / "podglad")
    assert p.preview == tmp_path / "podglad" / "strona_1_podglad.png"
    assert p.preview.stat().st_size > 0


def test_check_margins_format_text(tmp_path):
    pdf = a5_pdf(tmp_path, background() + text(4, 100))
    out = PM.format_text(PM.check_margins(pdf, "ulotka_a5"))
    assert out.startswith("strona 1: 148×210 mm, spad 2,5 mm – OSTRZEŻENIA")
    assert "⚠" in out


def test_check_margins_cli_exit_code(good_a5, tmp_path):
    bad = a5_pdf(tmp_path, rect(*A5_TRIM, BLUE), "zla.pdf")
    assert PM.main([str(good_a5), "ulotka_a5"]) == 0
    assert PM.main([str(bad), "ulotka_a5"]) == 1


# --- błędne dane wejściowe ---------------------------------------------------------

@pytest.mark.parametrize("bad", NOT_A_PATH)
def test_check_margins_not_a_path(bad):
    with pytest.raises(TypeError):
        PM.check_margins(bad, "ulotka_a5")


def test_check_margins_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        PM.check_margins(tmp_path / "nie_ma.pdf", "ulotka_a5")


def test_check_margins_directory_instead_of_file(tmp_path):
    with pytest.raises(IsADirectoryError):
        PM.check_margins(tmp_path, "ulotka_a5")


@pytest.mark.parametrize("name", ["pusty", "jpg", "tekst", "html", "sam_naglowek"])
def test_check_margins_not_a_pdf(not_pdf_files, name):
    with pytest.raises(B.InvalidPdfError):
        PM.check_margins(not_pdf_files[name], "ulotka_a5")


def test_check_margins_truncated_pdf(truncated_pdf):
    with pytest.raises(B.InvalidPdfError):
        PM.check_margins(truncated_pdf, "ulotka_a5")


def test_check_margins_password_protected(password_pdf):
    with pytest.raises(B.EncryptedPdfError):
        PM.check_margins(password_pdf, "ulotka_a5")


def test_check_margins_owner_locked_opens(owner_locked_pdf):
    """Strona 100×100 pt nie pasuje do A5 – ważne, że plik się otworzył."""
    assert check_one(owner_locked_pdf).codes == {"FORMAT_MISMATCH"}


def test_check_margins_unknown_product(good_a5):
    with pytest.raises(KeyError, match="Nieznany produkt"):
        PM.check_margins(good_a5, "ulotka_a7")


@pytest.mark.parametrize("bad", [None, 123, ["ulotka_a5"], {"id": "ulotka_a5"}])
def test_check_margins_product_wrong_type(good_a5, bad):
    with pytest.raises(TypeError):
        PM.check_margins(good_a5, bad)


@pytest.mark.parametrize("bad", [0, -200, 71, 301, 600, math.nan, math.inf])
def test_check_margins_render_dpi_out_of_range(good_a5, bad):
    with pytest.raises(ValueError):
        PM.check_margins(good_a5, "ulotka_a5", render_dpi=bad)


@pytest.mark.parametrize("bad", ["200", None, True, [200]])
def test_check_margins_render_dpi_wrong_type(good_a5, bad):
    with pytest.raises(TypeError):
        PM.check_margins(good_a5, "ulotka_a5", render_dpi=bad)


def test_check_margins_arguments_validated_before_file(tmp_path):
    """Zły argument zgłoszony od razu, nawet gdy pliku nie ma."""
    with pytest.raises(ValueError):
        PM.check_margins(tmp_path / "nie_ma.pdf", "ulotka_a5", render_dpi=0)
    with pytest.raises(KeyError):
        PM.check_margins(tmp_path / "nie_ma.pdf", "nie_ma_produktu")


# --- spady ---------------------------------------------------------------------------

def test_bleed_not_filled(tmp_path):
    """Tło kończy się na linii cięcia – w spadzie biało."""
    p = check_one(a5_pdf(tmp_path, rect(*A5_TRIM, BLUE)))
    assert "BLEED_NOT_FILLED" in p.codes
    assert p.status == "BŁĘDY"
    assert {f.side for f in p.findings if f.code == "BLEED_NOT_FILLED"} == {"left", "right", "top", "bottom"}


def test_no_bleed_with_content_at_edge(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((148, 210), content=rect(0, 0, 148, 210, BLUE))])
    p = check_one(pdf)
    assert p.analysed_bleed_mm == 0
    assert p.codes == {"NO_BLEED_CONTENT_AT_EDGE"}
    assert p.status == "BŁĘDY"


def test_no_bleed_white_background_is_ok(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((148, 210), content=text(30, 100, b"0 0 0 rg"))])
    p = check_one(pdf)
    assert p.codes == {"NO_BLEED_OK"}
    assert p.status == "OK"


def test_trimbox_equal_to_media_means_no_bleed(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((148, 210), (0, 0, 148, 210), None, text(30, 100, b"0 0 0 rg"))])
    assert check_one(pdf).analysed_bleed_mm == 0


def test_canva_crop_marks_ignored(tmp_path):
    """Eksport z Canvy ze znacznikami: czarne kreski poza spadem nie są błędem."""
    marks = (b"0 0 0 RG 0.3 w 0 12.5 m 8 12.5 l S 12.5 0 m 12.5 8 l S "
             b"165 222.5 m 173 222.5 l S 160.5 227 m 160.5 235 l S ")
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec(
        (173, 235), (12.5, 12.5, 160.5, 222.5), (10, 10, 163, 225),
        rect(10, 10, 163, 225, BLUE) + marks)])
    p = check_one(pdf)
    assert p.status == "OK"
    assert p.analysed_bleed_mm == 2.5


def test_trimbox_missing_page_with_bleed(tmp_path):
    """Brak TrimBox, strona 153×215 – rozpoznana jako A5 + spad."""
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((153, 215), content=background())])
    p = check_one(pdf)
    assert p.codes == {"TRIMBOX_MISSING"}
    assert p.analysed_bleed_mm == 2.5
    assert p.status == "OK"


@pytest.mark.parametrize("bleed,codes,status", [
    (1.0, {"BLEED_SIZE"}, "OSTRZEŻENIA"),     # za mały spad
    (2.0, {"BLEED_SIZE"}, "OSTRZEŻENIA"),
    (2.3, set(), "OK"),                        # w granicach tolerancji 0,3 mm
    (3.0, set(), "OK"),                        # większy spad (np. z InDesign) – w porządku
    (5.0, set(), "OK"),
])
def test_bleed_size(tmp_path, bleed, codes, status):
    w, h = 148 + 2 * bleed, 210 + 2 * bleed
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec(
        (w, h), (bleed, bleed, bleed + 148, bleed + 210), (0, 0, w, h), rect(0, 0, w, h, BLUE))])
    p = check_one(pdf)
    assert p.codes == codes
    assert p.status == status
    assert p.analysed_bleed_mm == min(bleed, 2.5)


def test_bleed_asymmetric(tmp_path):
    """Spad 2,5 mm, ale z prawej 5 mm – sprawdzane z najmniejszym."""
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec(
        (155.5, 215), A5_TRIM, (0, 0, 155.5, 215), rect(0, 0, 155.5, 215, BLUE))])
    p = check_one(pdf)
    assert p.codes == {"BLEED_ASYMMETRIC"}
    assert p.analysed_bleed_mm == 2.5


def test_bleed_missing_on_one_side(tmp_path):
    """Z lewej brak spadu – liczy się jak plik bez spadów, tło przy krawędzi = błąd."""
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec(
        (150.5, 215), (0, 2.5, 148, 212.5), (0, 0, 150.5, 215), rect(0, 0, 150.5, 215, BLUE))])
    p = check_one(pdf)
    assert p.analysed_bleed_mm == 0
    assert "NO_BLEED_CONTENT_AT_EDGE" in p.codes


# --- strefa bezpieczeństwa 3 mm --------------------------------------------------------

@pytest.mark.parametrize("distance", [0.5, 1.0, 1.5, 2.0, 2.5])
def test_element_in_safe_zone(tmp_path, distance):
    """Biały tekst na tle, `distance` mm od lewej linii cięcia."""
    p = check_one(a5_pdf(tmp_path, background() + text(2.5 + distance, 100)))
    found = [f for f in p.findings if f.code == "ELEMENT_IN_SAFE_ZONE"]
    assert [f.side for f in found] == ["left"]
    assert p.status == "OSTRZEŻENIA"
    # Silnik podaje odległość dokładnie dopiero od ok. 1,5 mm – bliżej zwraca dolną granicę pasa (0,4 mm).
    if distance >= 1.5:
        assert found[0].distance_mm == pytest.approx(distance, abs=0.3)
    else:
        assert found[0].distance_mm <= 1.5


@pytest.mark.xfail(strict=True, reason="silnik margins.py: tekst 2,5–3 mm od cięcia nie jest wykrywany "
                                       "(w pasie 0,4–3 mm jest tylko brzeg liter)")
def test_element_just_inside_safe_zone_known_gap(tmp_path):
    """Wymóg to 3 mm, więc tekst 2,8 mm od cięcia powinien dać ostrzeżenie."""
    p = check_one(a5_pdf(tmp_path, background() + text(2.5 + 2.8, 100)))
    assert "ELEMENT_IN_SAFE_ZONE" in p.codes


@pytest.mark.parametrize("distance", [3.5, 4.0, 5.0, 10.0])
def test_element_outside_safe_zone(tmp_path, distance):
    p = check_one(a5_pdf(tmp_path, background() + text(2.5 + distance, 100)))
    assert p.status == "OK"


@pytest.mark.parametrize("side,x,y", [
    ("left", 2.5 + 1.5, 100),
    ("right", 150.5 - 1.5 - TEXT_W, 100),
    ("top", 60, 212.5 - 1.5 - TEXT_H),
    ("bottom", 60, 2.5 + 1.5),
])
def test_element_in_safe_zone_each_side(tmp_path, side, x, y):
    """Tekst 1,5 mm od każdej z krawędzi – zgłoszony po właściwej stronie."""
    p = check_one(a5_pdf(tmp_path, background() + text(x, y)))
    assert {f.side for f in p.findings if f.code == "ELEMENT_IN_SAFE_ZONE"} == {side}


# --- ramki 5 mm ----------------------------------------------------------------------

@pytest.mark.parametrize("distance,code,status", [
    (2.0, "FRAME_TOO_CLOSE", "OSTRZEŻENIA"),
    (3.0, "FRAME_TOO_CLOSE", "OSTRZEŻENIA"),
    (4.0, "FRAME_TOO_CLOSE", "OSTRZEŻENIA"),
    (6.0, "FRAME_OK", "OK"),
    (7.0, "FRAME_OK", "OK"),
])
def test_frame_distance(tmp_path, distance, code, status):
    """Ramka (kontur 0,5 mm) `distance` mm od linii cięcia z każdej strony."""
    d = 2.5 + distance
    p = check_one(a5_pdf(tmp_path, frame(d, d, 153 - d, 215 - d)))
    assert code in p.codes
    assert p.status == status


# --- orientacja, obrót, format ---------------------------------------------------------

def test_format_mismatch_skips_analysis(tmp_path):
    """Strona A4 dla produktu A5 – błąd formatu, bez rasteryzacji."""
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((215, 302), (2.5, 2.5, 212.5, 299.5), (0, 0, 215, 302),
                                                  rect(0, 0, 215, 302, BLUE))])
    p = check_one(pdf)
    assert p.codes == {"FORMAT_MISMATCH"}
    assert p.status == "BŁĘDY"
    assert "210×297" in p.findings[0].message


def test_format_within_tolerance(tmp_path):
    """Netto 148,4×210,3 mm (zaokrąglenia eksportu) – nadal A5."""
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec(
        (153.4, 215.3), (2.5, 2.5, 150.9, 212.8), (0, 0, 153.4, 215.3), rect(0, 0, 153.4, 215.3, BLUE))])
    assert check_one(pdf).status == "OK"


def test_landscape_page_for_portrait_product(tmp_path):
    """A5 poziomo – produkt obracany do orientacji strony."""
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec(
        (215, 153), (2.5, 2.5, 212.5, 150.5), (0, 0, 215, 153), rect(0, 0, 215, 153, BLUE))])
    p = check_one(pdf)
    assert p.trim_size == (210, 148)
    assert p.status == "OK"


@pytest.mark.parametrize("rotate", [90, 180, 270])
def test_rotated_page(tmp_path, rotate):
    """/Rotate na stronie: tekst 1,5 mm od krawędzi wciąż wykryty."""
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((153, 215), A5_TRIM, A5_BLEED,
                                                  background() + text(4, 100), rotate)])
    p = check_one(pdf)
    assert "ELEMENT_IN_SAFE_ZONE" in p.codes
    assert sorted(p.trim_size) == [148, 210]


def test_folded_product_element_on_fold(tmp_path):
    """A4 składana do A5: tekst 1 mm od bigu (148,5 mm) – ostrzeżenie; 10 mm – w porządku."""
    w, h = 302, 215
    fold_x = 2.5 + 148.5
    for distance, expected in ((1.0, {"ELEMENT_NEAR_FOLD"}), (10.0, set())):
        content = rect(0, 0, w, h, BLUE) + text(fold_x + distance, 100)
        pdf = make_pdf(tmp_path / f"big_{distance}.pdf",
                       [page_spec((w, h), (2.5, 2.5, 299.5, 212.5), (0, 0, w, h), content)])
        assert check_one(pdf, "ulotka_a4_skladana_a5").codes == expected


def test_multipage_each_page_checked(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [
        page_spec((153, 215), A5_TRIM, A5_BLEED, background()),
        page_spec((153, 215), A5_TRIM, A5_BLEED, rect(*A5_TRIM, BLUE)),
        page_spec((215, 302), (2.5, 2.5, 212.5, 299.5), (0, 0, 215, 302)),
    ])
    pages = PM.check_margins(pdf, "ulotka_a5")
    assert [p.page for p in pages] == [1, 2, 3]
    assert [p.status for p in pages] == ["OK", "BŁĘDY", "BŁĘDY"]
    assert "BLEED_NOT_FILLED" in pages[1].codes
    assert pages[2].codes == {"FORMAT_MISMATCH"}


def test_empty_pdf_returns_empty_list(tmp_path):
    path = tmp_path / "pusty.pdf"
    with open(path, "wb") as f:
        PdfWriter().write(f)
    assert PM.check_margins(path, "ulotka_a5") == []


# --- rozdzielczość rasteryzacji ---------------------------------------------------------

@pytest.mark.parametrize("dpi", [72, 100, 150, 200, 250, 300])
@pytest.mark.parametrize("distance,codes", [(1.0, {"ELEMENT_IN_SAFE_ZONE"}),
                                            (2.5, {"ELEMENT_IN_SAFE_ZONE"}),   # tuż przy granicy
                                            (3.5, set())])
def test_result_stable_across_render_dpi(tmp_path, dpi, distance, codes):
    """Ten sam wynik w całym dozwolonym zakresie rozdzielczości rasteryzacji."""
    pdf = a5_pdf(tmp_path, background() + text(2.5 + distance, 100))
    p = check_one(pdf, render_dpi=dpi)
    assert p.render_dpi == dpi
    assert p.codes == codes


def test_render_dpi_reduced_for_large_format(tmp_path):
    """Baner 1000×2000 mm – rasteryzacja zmniejszona do limitu pikseli."""
    product = M.get_product(M.load_rules(), trim=(1000, 2000))
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec(
        (1005, 2005), (2.5, 2.5, 1002.5, 2002.5), (0, 0, 1005, 2005), rect(0, 0, 1005, 2005, BLUE))])
    p = check_one(pdf, product, render_dpi=300)
    assert "RENDER_DPI_REDUCED" in p.codes
    assert p.render_dpi < 300
    pixels = (1005 / 25.4 * p.render_dpi) * (2005 / 25.4 * p.render_dpi)
    assert pixels <= PM.MAX_RENDER_PIXELS * 1.01
    assert p.status == "OK"
