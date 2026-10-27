"""Testy color_spaces: happy path, błędne dane wejściowe, warianty przestrzeni barw."""
import sys
from pathlib import Path

import pytest
from conftest import NOT_A_PATH
from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, ByteStringObject, DecodedStreamObject,
                           DictionaryObject, NameObject, NumberObject)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "pdf-check" / "scripts"))

import pdf_boxes as B  # noqa: E402
import pdf_colors as C  # noqa: E402


# --- budowanie PDF-ów testowych -----------------------------------------------------

def to_pdf(value):
    """Zwykłe obiekty Pythona → obiekty pypdf ("/Nazwa" → NameObject)."""
    if isinstance(value, (DictionaryObject, ArrayObject, NameObject)) or hasattr(value, "idnum"):
        return value
    if isinstance(value, bool):
        return BooleanObject(value)
    if isinstance(value, int):
        return NumberObject(value)
    if isinstance(value, str):
        return NameObject(value)
    if isinstance(value, bytes):
        return ByteStringObject(value)
    if isinstance(value, (list, tuple)):
        return ArrayObject(to_pdf(v) for v in value)
    if isinstance(value, dict):
        return DictionaryObject({NameObject(k): to_pdf(v) for k, v in value.items()})
    return value


class Doc:
    """PDF-owy „plac budowy”: obiekty pośrednie + strony z treścią i zasobami."""

    def __init__(self):
        self.w = PdfWriter()

    def stream(self, data: bytes, **entries):
        s = DecodedStreamObject()
        s.set_data(data)
        s.update(to_pdf(entries))
        return self.w._add_object(s)

    def icc(self, n):
        return self.stream(b"icc", **{"/N": n})

    def image(self, colorspace, mask=False):
        entries = {"/Type": "/XObject", "/Subtype": "/Image", "/Width": 1, "/Height": 1,
                   "/BitsPerComponent": 1 if mask else 8}
        if mask:
            entries["/ImageMask"] = True
        else:
            entries["/ColorSpace"] = colorspace
        return self.stream(b"\x00\x00\x00\x00", **entries)

    def form(self, content: bytes, resources=None):
        entries = {"/Type": "/XObject", "/Subtype": "/Form", "/BBox": [0, 0, 100, 100]}
        if resources is not None:
            entries["/Resources"] = resources
        return self.stream(content, **entries)

    def page(self, content: bytes = b"", resources=None):
        page = self.w.add_blank_page(width=100, height=100)
        if content:
            page[NameObject("/Contents")] = self.stream(content)
        page[NameObject("/Resources")] = to_pdf(resources or {})
        return page

    def save(self, path: Path) -> Path:
        with open(path, "wb") as f:
            self.w.write(f)
        return path


def one_page(tmp_path, content: bytes, resources=None, build=None):
    """PDF z jedną stroną → PageColors tej strony. `build(doc)` może zwrócić zasoby."""
    doc = Doc()
    if build is not None:
        resources = build(doc)
    doc.page(content, resources)
    return C.color_spaces(doc.save(tmp_path / "t.pdf"))[0]


# --- happy path: plik „PDF do druku (CMYK)” ze złoceniem ---------------------------

@pytest.fixture
def print_ready(tmp_path):
    """Tekst w CMYK, zdjęcie w ICC CMYK, element złocony jako spot „Gold”."""
    doc = Doc()
    resources = {
        "/XObject": {"/Im0": doc.image(["/ICCBased", doc.icc(4)])},
        "/ColorSpace": {"/CS0": ["/Separation", "/Gold", "/DeviceCMYK", doc.icc(4)]},
    }
    doc.page(b"0 0 0 1 k BT ET q /Im0 Do Q /CS0 cs 1 scn 0 0 10 10 re f", resources)
    return doc.save(tmp_path / "druk.pdf")


def test_color_spaces_happy_path(print_ready):
    pages = C.color_spaces(print_ready)
    assert isinstance(pages, list) and len(pages) == 1

    p = pages[0]
    assert isinstance(p, C.PageColors)
    assert p.page == 1
    assert p.images == {"CMYK": 1}
    assert p.vector == {"CMYK", "Spot"}
    assert p.spot_names == {"Gold"}
    assert p.has_rgb is False


def test_color_spaces_happy_path_standard_canva_export(tmp_path):
    """Zwykły eksport PDF z Canvy: wszystko w RGB."""
    p = one_page(tmp_path, b"1 0 0 rg 0 0 10 10 re f /Im0 Do",
                 build=lambda d: {"/XObject": {"/Im0": d.image(["/ICCBased", d.icc(3)])}})
    assert p.images == {"RGB": 1}
    assert p.vector == {"RGB"}
    assert p.spot_names == set()
    assert p.has_rgb is True


def test_accepts_str_path(print_ready):
    assert C.color_spaces(str(print_ready))[0].images == {"CMYK": 1}


def test_format_text(print_ready, tmp_path):
    assert C.format_text(C.color_spaces(print_ready)) == (
        "strona 1: obrazy CMYK×1 | wektor/tekst CMYK, Spot | spot: Gold")
    rgb = one_page(tmp_path, b"1 0 0 rg")
    assert C.format_text([rgb]).endswith("| RGB!")


# --- błędne dane wejściowe ---------------------------------------------------------

@pytest.mark.parametrize("bad", NOT_A_PATH)
def test_color_spaces_not_a_path(bad):
    with pytest.raises(TypeError):
        C.color_spaces(bad)


def test_color_spaces_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="Nie ma pliku"):
        C.color_spaces(tmp_path / "nie_ma.pdf")


def test_color_spaces_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        C.color_spaces(tmp_path / "brak_folderu" / "plik.pdf")


def test_color_spaces_directory_instead_of_file(tmp_path):
    with pytest.raises(IsADirectoryError):
        C.color_spaces(tmp_path)


def test_color_spaces_empty_string():
    # Path("") == "." – katalog bieżący, nie plik
    with pytest.raises(IsADirectoryError):
        C.color_spaces("")


@pytest.mark.parametrize("name", ["pusty", "jpg", "tekst", "html", "sam_naglowek"])
def test_color_spaces_not_a_pdf(not_pdf_files, name):
    with pytest.raises(B.InvalidPdfError):
        C.color_spaces(not_pdf_files[name])


def test_color_spaces_truncated_pdf(truncated_pdf):
    with pytest.raises(B.InvalidPdfError):
        C.color_spaces(truncated_pdf)


def test_color_spaces_password_protected(password_pdf):
    with pytest.raises(B.EncryptedPdfError, match="hasłem"):
        C.color_spaces(password_pdf)


def test_color_spaces_owner_locked_opens(owner_locked_pdf):
    """Blokada edycji to nie problem – plik da się przeczytać bez hasła."""
    assert len(C.color_spaces(owner_locked_pdf)) == 1


def test_invalid_pdf_errors_are_value_errors():
    assert issubclass(B.InvalidPdfError, ValueError)
    assert issubclass(B.EncryptedPdfError, B.InvalidPdfError)


def test_color_spaces_broken_page_content(tmp_path):
    """„cs” bez nazwy przestrzeni – uszkodzona treść strony."""
    with pytest.raises(B.InvalidPdfError):
        one_page(tmp_path, b"cs")

# --- operatory koloru ---------------------------------------------------------------

@pytest.mark.parametrize("content,expected", [
    (b"1 0 0 rg", {"RGB"}), (b"1 0 0 RG", {"RGB"}),
    (b"0 0 0 1 k", {"CMYK"}), (b"0 0 0 1 K", {"CMYK"}),
    (b"0.5 g", {"Gray"}), (b"0.5 G", {"Gray"}),
    (b"/DeviceRGB cs", {"RGB"}), (b"/DeviceCMYK CS", {"CMYK"}), (b"/DeviceGray cs", {"Gray"}),
    (b"/Pattern cs", {"Pattern"}),
    (b"1 0 0 rg 0 0 0 1 k 0.5 g", {"RGB", "CMYK", "Gray"}),
])
def test_vector_operators(tmp_path, content, expected):
    p = one_page(tmp_path, content)
    assert p.vector == expected
    assert p.images == {}


def test_empty_page(tmp_path):
    p = one_page(tmp_path, b"")
    assert (p.images, p.vector, p.spot_names, p.has_rgb) == ({}, set(), set(), False)


# --- przestrzenie nazwane w zasobach -------------------------------------------------

@pytest.mark.parametrize("make_cs,expected", [
    (lambda d: ["/ICCBased", d.icc(1)], "Gray"),
    (lambda d: ["/ICCBased", d.icc(3)], "RGB"),
    (lambda d: ["/ICCBased", d.icc(4)], "CMYK"),
    (lambda d: ["/ICCBased", d.icc(2)], "Unknown"),
    (lambda d: ["/CalRGB", {"/WhitePoint": [1, 1, 1]}], "RGB"),
    (lambda d: ["/CalGray", {"/WhitePoint": [1, 1, 1]}], "Gray"),
    (lambda d: ["/Lab", {"/WhitePoint": [1, 1, 1]}], "Lab"),
    (lambda d: ["/Pattern", "/DeviceRGB"], "RGB"),
    (lambda d: "/DeviceCMYK", "CMYK"),        # alias nazwy na przestrzeń urządzenia
])
def test_named_colorspace(tmp_path, make_cs, expected):
    p = one_page(tmp_path, b"/CS0 cs", build=lambda d: {"/ColorSpace": {"/CS0": make_cs(d)}})
    assert p.vector == {expected}


def test_named_colorspace_missing_from_resources(tmp_path):
    """Odwołanie do nieistniejącej przestrzeni – „Unknown”, bez wyjątku."""
    assert one_page(tmp_path, b"/CS9 cs").vector == {"Unknown"}


# --- kolory dodatkowe: Separation i DeviceN -------------------------------------------

@pytest.mark.parametrize("colorants,family,category,spots", [
    (["/Gold"], "/Separation", "Spot", {"Gold"}),
    (["/Cyan"], "/Separation", "CMYK", set()),            # kanał procesowy, nie spot
    (["/All"], "/Separation", "Registration", set()),     # znaczniki cięcia z Canvy
    (["/Cyan", "/Magenta"], "/DeviceN", "CMYK", set()),
    (["/Black", "/Gold"], "/DeviceN", "Spot", {"Gold"}),
    (["/White", "/Silver"], "/DeviceN", "Spot", {"White", "Silver"}),   # tonery specjalne
])
def test_spot_colors(tmp_path, colorants, family, category, spots):
    def build(d):
        names = colorants[0] if family == "/Separation" else colorants
        return {"/ColorSpace": {"/CS0": [family, names, "/DeviceCMYK", d.icc(4)]}}
    p = one_page(tmp_path, b"/CS0 cs", build=build)
    assert p.vector == {category}
    assert p.spot_names == spots


def test_separation_none_is_ignored(tmp_path):
    p = one_page(tmp_path, b"/CS0 cs",
                 build=lambda d: {"/ColorSpace": {"/CS0": ["/Separation", "/None", "/DeviceGray", d.icc(1)]}})
    assert p.vector == set()


# --- obrazy -------------------------------------------------------------------------

@pytest.mark.parametrize("make_cs,expected", [
    (lambda d: "/DeviceRGB", "RGB"),
    (lambda d: "/DeviceCMYK", "CMYK"),
    (lambda d: "/DeviceGray", "Gray"),
    (lambda d: ["/Indexed", "/DeviceRGB", 1, b"\x00" * 6], "RGB"),       # paleta nad RGB
    (lambda d: ["/Indexed", ["/ICCBased", d.icc(4)], 0, b"\x00" * 4], "CMYK"),
    (lambda d: None, "Unknown"),                                          # np. JPX bez ColorSpace
])
def test_image_colorspace(tmp_path, make_cs, expected):
    def build(d):
        cs = make_cs(d)
        img = d.image(cs) if cs is not None else d.stream(
            b"\x00", **{"/Type": "/XObject", "/Subtype": "/Image", "/Width": 1, "/Height": 1})
        return {"/XObject": {"/Im0": img}}
    p = one_page(tmp_path, b"/Im0 Do", build=build)
    assert p.images == {expected: 1}
    assert p.vector == set()


def test_image_mask_not_counted_as_image(tmp_path):
    """Maska obrazu maluje kolorem wypełnienia – liczy się tylko ten kolor."""
    p = one_page(tmp_path, b"0 0 0 1 k /M0 Do", build=lambda d: {"/XObject": {"/M0": d.image(None, mask=True)}})
    assert p.images == {}
    assert p.vector == {"CMYK"}


def test_unused_image_in_resources_not_counted(tmp_path):
    p = one_page(tmp_path, b"0 0 0 1 k", build=lambda d: {"/XObject": {"/Im0": d.image("/DeviceRGB")}})
    assert p.images == {}
    assert p.has_rgb is False


def test_same_image_drawn_twice(tmp_path):
    p = one_page(tmp_path, b"/Im0 Do /Im0 Do", build=lambda d: {"/XObject": {"/Im0": d.image("/DeviceRGB")}})
    assert p.images == {"RGB": 2}


def test_mixed_images(tmp_path):
    p = one_page(tmp_path, b"/A Do /B Do /C Do", build=lambda d: {"/XObject": {
        "/A": d.image("/DeviceRGB"), "/B": d.image("/DeviceCMYK"), "/C": d.image("/DeviceCMYK")}})
    assert p.images == {"RGB": 1, "CMYK": 2}


def test_unknown_xobject_name_ignored(tmp_path):
    assert one_page(tmp_path, b"/Brak Do").images == {}


@pytest.mark.parametrize("settings,expected", [
    (b"/CS /RGB", {"RGB": 1}), (b"/CS /G", {"Gray": 1}), (b"/CS /CMYK", {"CMYK": 1}),
    (b"/ColorSpace /DeviceRGB", {"RGB": 1}),
    (b"/IM true", {}),                                    # maska w treści
])
def test_inline_image(tmp_path, settings, expected):
    content = b"BI /W 1 /H 1 /BPC 8 " + settings + b" ID \x00\x00\x00\x00 EI"
    assert one_page(tmp_path, content).images == expected


# --- formularze (Form XObject) i cieniowania -----------------------------------------

def test_rgb_image_inside_form(tmp_path):
    """Obraz RGB schowany w grupie (Form XObject) z własnymi zasobami."""
    def build(d):
        inner = {"/XObject": {"/Im0": d.image("/DeviceRGB")}}
        return {"/XObject": {"/Fm0": d.form(b"1 0 0 rg /Im0 Do", inner)}}
    p = one_page(tmp_path, b"/Fm0 Do", build=build)
    assert p.images == {"RGB": 1}
    assert p.vector == {"RGB"}


def test_form_without_resources_uses_page_resources(tmp_path):
    def build(d):
        return {"/XObject": {"/Fm0": d.form(b"/Im0 Do"), "/Im0": d.image("/DeviceCMYK")}}
    assert one_page(tmp_path, b"/Fm0 Do", build=build).images == {"CMYK": 1}


def test_nested_forms(tmp_path):
    def build(d):
        f2 = d.form(b"/Im0 Do", {"/XObject": {"/Im0": d.image("/DeviceRGB")}})
        f1 = d.form(b"/F2 Do", {"/XObject": {"/F2": f2}})
        return {"/XObject": {"/F1": f1}}
    assert one_page(tmp_path, b"/F1 Do", build=build).images == {"RGB": 1}


def test_self_referencing_form_does_not_loop(tmp_path):
    def build(d):
        fm = d.form(b"0 0 0 1 k /Fm0 Do")
        fm.get_object()[NameObject("/Resources")] = to_pdf({"/XObject": {"/Fm0": fm}})
        return {"/XObject": {"/Fm0": fm}}
    assert one_page(tmp_path, b"/Fm0 Do", build=build).vector == {"CMYK"}


@pytest.mark.parametrize("cs,expected", [("/DeviceRGB", "RGB"), ("/DeviceCMYK", "CMYK")])
def test_shading(tmp_path, cs, expected):
    def build(d):
        sh = {"/ShadingType": 2, "/ColorSpace": cs, "/Coords": [0, 0, 1, 0]}
        return {"/Shading": {"/Sh0": sh}}
    assert one_page(tmp_path, b"/Sh0 sh", build=build).vector == {expected}


# --- wiele stron ---------------------------------------------------------------------

def test_multipage(tmp_path):
    doc = Doc()
    doc.page(b"0 0 0 1 k")
    doc.page(b"/Im0 Do", {"/XObject": {"/Im0": doc.image("/DeviceRGB")}})
    doc.page(b"")
    pages = C.color_spaces(doc.save(tmp_path / "t.pdf"))
    assert [p.page for p in pages] == [1, 2, 3]
    assert [p.has_rgb for p in pages] == [False, True, False]
    assert pages[1].images == {"RGB": 1}


def test_empty_pdf_returns_empty_list(tmp_path):
    assert C.color_spaces(Doc().save(tmp_path / "t.pdf")) == []
