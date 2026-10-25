"""Testy check_pdf: happy path, błędne dane wejściowe, warianty raportu i CLI."""
import json
import sys
from pathlib import Path

import pytest
from conftest import NOT_A_PATH
from test_pdf_margins import A5_BLEED, A5_TRIM, make_pdf, page_spec, rect, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "pdf-check" / "scripts"))

import check_pdf as CP  # noqa: E402
import pdf_boxes as B  # noqa: E402

CMYK_BG = b"0.8 0.4 0 0 k 0 0 153 215 re f "
WHITE_CMYK = b"0 0 0 0 k"


def a5(tmp_path, content: bytes, name="a5.pdf") -> Path:
    return make_pdf(tmp_path / name, [page_spec((153, 215), A5_TRIM, A5_BLEED, content)])


# --- happy path: ulotka A5 w CMYK, poprawne spady i marginesy -----------------------

@pytest.fixture
def good_pdf(tmp_path):
    return a5(tmp_path, CMYK_BG + text(30, 100, WHITE_CMYK), "dobra.pdf")


def test_check_pdf_happy_path(good_pdf):
    report = CP.check_pdf(good_pdf, "ulotka_a5")
    assert report["file"] == str(good_pdf)
    assert report["product"] == {"id": "ulotka_a5", "name": "Ulotka A5", "trim_mm": [148.0, 210.0]}
    assert report["status"] == "OK"
    assert report["general"] == []
    assert len(report["pages"]) == 1

    page = report["pages"][0]
    assert page["page"] == 1
    assert page["trim_mm"] == [148, 210]
    assert page["bleed_mm"] == {"left": 2.5, "right": 2.5, "top": 2.5, "bottom": 2.5}
    assert page["trimbox"] is True
    assert page["crop_marks"] is False
    assert page["colors"] == {"images": {}, "vector": ["CMYK"], "spots": []}
    assert page["analysed_bleed_mm"] == 2.5
    assert page["render_dpi"] == 200
    assert page["status"] == "OK"
    assert page["findings"] == []
    json.dumps(report, ensure_ascii=False)          # raport da się zapisać jako JSON


def test_check_pdf_preview(good_pdf, tmp_path):
    report = CP.check_pdf(good_pdf, "ulotka_a5", preview_dir=tmp_path / "pv")
    assert Path(report["pages"][0]["preview"]).is_file()


def test_check_pdf_format_text(good_pdf):
    out = CP.format_text(CP.check_pdf(good_pdf, "ulotka_a5"))
    assert out.splitlines()[1:3] == ["Produkt: Ulotka A5", "WYNIK: OK"]
    assert "-- strona 1: 148×210 mm, znaczniki cięcia: nie – OK" in out


# --- błędne dane wejściowe ---------------------------------------------------------

@pytest.mark.parametrize("bad", NOT_A_PATH)
def test_check_pdf_not_a_path(bad):
    with pytest.raises(TypeError):
        CP.check_pdf(bad, "ulotka_a5")


def test_check_pdf_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        CP.check_pdf(tmp_path / "nie_ma.pdf", "ulotka_a5")


@pytest.mark.parametrize("name", ["pusty", "jpg", "tekst", "html", "sam_naglowek"])
def test_check_pdf_not_a_pdf(not_pdf_files, name):
    with pytest.raises(B.InvalidPdfError):
        CP.check_pdf(not_pdf_files[name], "ulotka_a5")


def test_check_pdf_password_protected(password_pdf):
    with pytest.raises(B.EncryptedPdfError):
        CP.check_pdf(password_pdf, "ulotka_a5")


def test_check_pdf_unknown_product(good_pdf):
    with pytest.raises(KeyError):
        CP.check_pdf(good_pdf, "ulotka_a7")


@pytest.mark.parametrize("bad", [123, ["ulotka_a5"]])
def test_check_pdf_product_wrong_type(good_pdf, bad):
    with pytest.raises(TypeError):
        CP.check_pdf(good_pdf, bad)


# --- warianty raportu ----------------------------------------------------------------

def test_without_product_only_geometry_and_colors(good_pdf):
    report = CP.check_pdf(good_pdf)
    assert "product" not in report
    assert [f["code"] for f in report["general"]] == ["PRODUCT_UNKNOWN"]
    assert "Ulotka A5" in report["general"][0]["message"]
    assert report["status"] == "DO_WERYFIKACJI"
    assert "analysed_bleed_mm" not in report["pages"][0]


def test_rgb_reported_as_info(tmp_path):
    pdf = a5(tmp_path, rect(0, 0, 153, 215, b"0.2 0.4 0.8 rg"))
    page = CP.check_pdf(pdf, "ulotka_a5")["pages"][0]
    assert [(f["code"], f["severity"]) for f in page["findings"]] == [("RGB", "INFO")]
    assert page["status"] == "OK"


def test_spot_color_needs_review(tmp_path):
    """Kolor dodatkowy „Gold” – do sprawdzenia, czy to warstwa złocenia."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject
    pdf = a5(tmp_path, CMYK_BG + b"/CS0 cs 1 scn 20 20 30 30 re f ")
    w = PdfWriter(clone_from=PdfReader(pdf))
    res = w.pages[0]["/Resources"]
    res[NameObject("/ColorSpace")] = DictionaryObject({NameObject("/CS0"): ArrayObject(
        [NameObject("/Separation"), NameObject("/Gold"), NameObject("/DeviceCMYK"), NameObject("/DeviceCMYK")])})
    w.write(pdf)
    page = CP.check_pdf(pdf, "ulotka_a5")["pages"][0]
    assert page["colors"]["spots"] == ["Gold"]
    assert "SPOT_COLOR" in {f["code"] for f in page["findings"]}
    assert page["status"] == "DO_WERYFIKACJI"


def test_crop_marks_registration_not_listed_as_color(tmp_path):
    """Znaczniki cięcia w kolorze „All” nie trafiają do listy kolorów."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec(
        (173, 235), (12.5, 12.5, 160.5, 222.5), (10, 10, 163, 225),
        b"0.8 0.4 0 0 k 10 10 153 215 re f /CS0 CS 1 SCN 0.3 w 0 12.5 m 8 12.5 l S ")])
    w = PdfWriter(clone_from=PdfReader(pdf))
    w.pages[0]["/Resources"][NameObject("/ColorSpace")] = DictionaryObject({NameObject("/CS0"): ArrayObject(
        [NameObject("/Separation"), NameObject("/All"), NameObject("/DeviceCMYK"), NameObject("/DeviceCMYK")])})
    w.write(pdf)
    page = CP.check_pdf(pdf, "ulotka_a5")["pages"][0]
    assert page["crop_marks"] is True
    assert page["colors"]["vector"] == ["CMYK"]
    assert page["status"] == "OK"


def test_errors_set_overall_status(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [
        page_spec((153, 215), A5_TRIM, A5_BLEED, CMYK_BG),
        page_spec((153, 215), A5_TRIM, A5_BLEED, b"0.8 0.4 0 0 k 2.5 2.5 148 210 re f "),
    ])
    report = CP.check_pdf(pdf, "ulotka_a5")
    assert [p["status"] for p in report["pages"]] == ["OK", "BŁĘDY"]
    assert report["status"] == "BŁĘDY"


def test_empty_pdf(tmp_path):
    from pypdf import PdfWriter
    path = tmp_path / "pusty.pdf"
    with open(path, "wb") as f:
        PdfWriter().write(f)
    report = CP.check_pdf(path, "ulotka_a5")
    assert report["pages"] == []
    assert [f["code"] for f in report["general"]] == ["NO_PAGES"]
    assert report["status"] == "BŁĘDY"


# --- CLI ---------------------------------------------------------------------------------

def test_cli_exit_codes(good_pdf, tmp_path, capsys):
    warn = a5(tmp_path, CMYK_BG + text(4, 100, WHITE_CMYK), "ostrzezenie.pdf")
    bad = a5(tmp_path, b"0.8 0.4 0 0 k 2.5 2.5 148 210 re f ", "blad.pdf")
    assert CP.main([str(good_pdf), "--product", "ulotka_a5"]) == 0
    assert CP.main([str(warn), "--product", "ulotka_a5"]) == 1
    assert CP.main([str(bad), "--product", "ulotka_a5"]) == 2
    assert CP.main([str(tmp_path / "nie_ma.pdf"), "--product", "ulotka_a5"]) == 3
    assert "NIE_DA_SIĘ_SPRAWDZIĆ" in capsys.readouterr().out


def test_cli_json(good_pdf, capsys):
    assert CP.main([str(good_pdf), "--product", "ulotka_a5", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "OK"


def test_cli_custom_trim(tmp_path, capsys):
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((105, 205), (2.5, 2.5, 102.5, 202.5), (0, 0, 105, 205),
                                                  b"0.8 0.4 0 0 k 0 0 105 205 re f ")])
    assert CP.main([str(pdf), "--trim", "100x200", "--json"]) == 0
    assert "Format niestandardowy 100×200 mm" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--product", "ulotka_a7"], ["--trim", "100x200", "--folds", "x"]])
def test_cli_bad_product_arguments(good_pdf, args):
    assert CP.main([str(good_pdf)] + args) == 3


def test_cli_list_products(capsys):
    assert CP.main(["--list-products"]) == 0
    assert "ulotka_a5" in capsys.readouterr().out
