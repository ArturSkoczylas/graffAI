"""Przypadki z prawdziwych plików od drukarni (listopad 2026), odtworzone syntetycznie.

Prawdziwe pliki zawierają dane klientów, więc nie trafiają do repo (samples/ jest w .gitignore).
Tu każdy przypadek jest odtworzony w samej geometrii, bez treści klienta.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "skills" / "margin-check" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "pdf-check" / "scripts"))

import check_image  # noqa: E402
import margins as M  # noqa: E402
import pdf_boxes as B  # noqa: E402
from sample_factory import Canvas  # noqa: E402
from test_pdf_margins import BLUE, WHITE, check_one, make_pdf, page_spec, rect, text  # noqa: E402

RULES = M.load_rules()
DARK = b"0.05 0.05 0.05 rg"
TEAL = b"0.1 0.4 0.4 rg"


def _codes(report):
    codes = {f["code"] for f in report.get("general", [])}
    for p in report["pages"]:
        codes |= {f["code"] for f in p["findings"]}
    return codes


# --- 02: wizytówka z Canvy 88,9×50,8 mm (3,5×2 cala) zamiast 90×50 -------------------

def canva_card_pdf(tmp_path, content=b""):
    """Jak eksport z Canvy: netto 88,9×50,8, spad 3 mm, 3 mm marginesu na znaczniki."""
    w, h, b, m = 88.9, 50.8, 3.0, 3.0
    media = (w + 2 * (b + m), h + 2 * (b + m))
    trim = (b + m, b + m, b + m + w, b + m + h)
    bleed = (m, m, m + w + 2 * b, m + h + 2 * b)
    bg = rect(m, m, m + w + 2 * b, m + h + 2 * b, DARK)
    return make_pdf(tmp_path / "canva.pdf", [page_spec(media, trim, bleed, bg + content)])


def test_canva_card_format_close_is_not_an_error(tmp_path):
    p = check_one(canva_card_pdf(tmp_path), "wizytowka_90x50")
    assert "FORMAT_CLOSE" in p.codes and "FORMAT_MISMATCH" not in p.codes
    assert p.status == "DO_WERYFIKACJI"


def test_canva_card_margins_still_checked(tmp_path):
    """Przy formacie „prawie” zgodnym marginesy dalej są sprawdzane."""
    # tekst 1 mm od lewej linii cięcia (netto zaczyna się 6 mm od brzegu arkusza)
    p = check_one(canva_card_pdf(tmp_path, text(6 + 1.0, 30, WHITE)), "wizytowka_90x50")
    assert "ELEMENT_IN_SAFE_ZONE" in p.codes


def test_canva_crop_marks_with_3mm_margin_detected(tmp_path):
    assert B.read_boxes(canva_card_pdf(tmp_path))[0].has_crop_marks is True


def test_format_far_off_still_mismatch(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((90, 60), (2.5, 2.5, 87.5, 57.5), (0, 0, 90, 60),
                                                  rect(0, 0, 90, 60, BLUE))])
    p = check_one(pdf, "wizytowka_90x50")
    assert "FORMAT_MISMATCH" in p.codes and p.status == "BŁĘDY"


def test_canva_card_image_with_dpi_metadata(tmp_path):
    """To samo dla JPG: wymiary w mm znane z metadanych DPI."""
    c = Canvas(88.9, 50.8, bleed=2.5, dpi=600, bg=(20, 20, 20))
    path = c.save(tmp_path / "canva.jpg", quality=92)
    rep = check_image.check_file(path, M.get_product(RULES, "wizytowka_90x50"), RULES)
    assert "FORMAT_CLOSE" in _codes(rep) and "FORMAT_MISMATCH" not in _codes(rep)
    assert rep["status"] == "DO_WERYFIKACJI"


# --- 05: zaproszenie składane przysłane jako osobne strony 140×140 --------------------

def test_folded_invitation_single_page_image(tmp_path):
    c = Canvas(140, 140, bleed=2.5, dpi=300, bg=(250, 230, 235))
    path = c.save(tmp_path / "strona1.jpg", quality=92)
    rep = check_image.check_file(path, M.get_product(RULES, "zaproszenie_skladane_280x140"), RULES)
    codes = _codes(rep)
    assert "FOLDED_AS_PAGES" in codes and "FORMAT_MISMATCH" not in codes
    msg = next(f["message"] for f in rep["pages"][0]["findings"] if f["code"] == "FOLDED_AS_PAGES")
    assert "285×145" in msg and "rozkładówki" in msg


def test_folded_invitation_single_page_without_bleed_reports_bleed(tmp_path):
    """Panel bez spadów z tłem do krawędzi: oprócz rozkładówki zgłoszony brak spadów."""
    c = Canvas(140, 140, bleed=0, dpi=300, bg=(250, 200, 210))
    path = c.save(tmp_path / "strona1.jpg", quality=92)
    rep = check_image.check_file(path, M.get_product(RULES, "zaproszenie_skladane_280x140"), RULES)
    assert {"FOLDED_AS_PAGES", "NO_BLEED_CONTENT_AT_EDGE"} <= _codes(rep)


def test_folded_invitation_single_page_pdf(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [page_spec((145, 145), (2.5, 2.5, 142.5, 142.5), (0, 0, 145, 145),
                                                  rect(0, 0, 145, 145, BLUE))])
    p = check_one(pdf, "zaproszenie_skladane_280x140")
    assert "FOLDED_AS_PAGES" in p.codes and "FORMAT_MISMATCH" not in p.codes


# --- 04: granica dwóch kolorów tła przecinająca krawędź to nie „element” ---------------

def two_panel_pdf(tmp_path, content=b""):
    """Wizytówka 85×55 ze spadem: lewa połowa biała, prawa morska (granica na x = 40 mm)."""
    bg = rect(0, 0, 90, 60, b"1 1 1 rg") + rect(2.5 + 40, 0, 90, 60, TEAL)
    return make_pdf(tmp_path / "a.pdf", [page_spec((90, 60), (2.5, 2.5, 87.5, 57.5), (0, 0, 90, 60),
                                                  bg + content)])


def test_color_boundary_across_edge_is_not_element(tmp_path):
    p = check_one(two_panel_pdf(tmp_path), "wizytowka_85x55")
    assert "ELEMENT_IN_SAFE_ZONE" not in p.codes
    assert p.status == "OK"


def test_text_next_to_color_boundary_still_detected(tmp_path):
    """Granica jest maskowana, ale tekst 1 mm od górnej krawędzi obok niej nadal jest wykrywany."""
    from test_pdf_margins import TEXT_H
    p = check_one(two_panel_pdf(tmp_path, text(2.5 + 50, 57.5 - 1.0 - TEXT_H, b"1 1 1 rg")),
                  "wizytowka_85x55")
    found = [f for f in p.findings if f.code == "ELEMENT_IN_SAFE_ZONE"]
    assert [f.side for f in found] == ["top"]


def test_color_boundary_image(tmp_path):
    c = Canvas(85, 55, bleed=2.5, dpi=600)
    c.rect(40, -2.5, 87.5, 57.5, fill=(20, 100, 100))
    path = c.save(tmp_path / "tyl.jpg", quality=92)
    rep = check_image.check_file(path, M.get_product(RULES, "wizytowka_85x55"), RULES)
    assert "ELEMENT_IN_SAFE_ZONE" not in _codes(rep)


# --- podglądy różnych PDF-ów nie nadpisują się ----------------------------------------

def test_pdf_previews_named_after_file(tmp_path):
    a = canva_card_pdf(tmp_path)
    b = make_pdf(tmp_path / "druga.pdf", [page_spec((90, 60), (2.5, 2.5, 87.5, 57.5), (0, 0, 90, 60),
                                                    rect(0, 0, 90, 60, BLUE))])
    pa = check_one(a, "wizytowka_90x50", preview_dir=tmp_path / "pv")
    pb = check_one(b, "wizytowka_85x55", preview_dir=tmp_path / "pv")
    assert pa.preview != pb.preview and pa.preview.exists() and pb.preview.exists()
