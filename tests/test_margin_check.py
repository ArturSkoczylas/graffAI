import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "margin-check" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import check_image  # noqa: E402
import canva_link  # noqa: E402
import margins as M  # noqa: E402
from sample_factory import build_all  # noqa: E402

RULES = M.load_rules()


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("samples"))


def _codes(report):
    codes = {f["code"] for f in report.get("general", [])}
    for p in report["pages"]:
        codes |= {f["code"] for f in p["findings"]}
    return codes


@pytest.mark.parametrize("name", [
    "a5_poprawna", "a5_brak_spadow", "a5_bez_spadow_biale_tlo", "a5_tekst_przy_krawedzi",
    "a5_tlo_nie_w_spadzie", "wizytowka_ramka_za_blisko", "wizytowka_ramka_ok",
    "wizytowka_niska_rozdzielczosc", "dl_tekst_na_bigu", "a5_metadane_72dpi",
    "a5_zly_format", "a5_zdjecie_w_tle", "a5_przezroczysty",
])
def test_sample(samples, name, tmp_path):
    path, product_id, expected_codes, expected_status = samples[name]
    product = M.get_product(RULES, product_id)
    report = check_image.check_file(Path(path), product, RULES, tmp_path)
    codes = _codes(report)
    assert expected_codes <= codes, f"{name}: brak {expected_codes - codes}, są {codes}"
    assert report["status"] == expected_status, f"{name}: {report['status']} / {codes}"


def test_good_files_have_no_false_alarms(samples, tmp_path):
    for name in ("a5_poprawna", "wizytowka_ramka_ok", "a5_metadane_72dpi"):
        path, pid, _, _ = samples[name]
        report = check_image.check_file(Path(path), M.get_product(RULES, pid), RULES, tmp_path)
        bad = [f for p in report["pages"] for f in p["findings"]
               if f["severity"] != "INFO"]
        assert not bad, f"{name}: {bad}"


def test_preview_created(samples, tmp_path):
    path, pid, _, _ = samples["a5_tekst_przy_krawedzi"]
    report = check_image.check_file(Path(path), M.get_product(RULES, pid), RULES, tmp_path)
    assert Path(report["pages"][0]["preview"]).exists()


def test_layout_detection_with_and_without_bleed():
    p = M.get_product(RULES, "ulotka_a5")
    with_bleed, _ = M.detect_layout(1807, 2539, p)        # 153×215 mm @300
    no_bleed, _ = M.detect_layout(1748, 2480, p)          # 148×210 mm @300
    assert with_bleed.has_bleed and round(with_bleed.dpi) == 300
    assert not no_bleed.has_bleed and round(no_bleed.dpi) == 300


def test_rotated_product():
    p = M.get_product(RULES, "ulotka_a5")
    lay, prod = M.detect_layout(2539, 1807, p)            # poziomo
    assert lay.rotated and prod.trim_w == 210


def test_custom_trim():
    p = M.get_product(RULES, trim=(100, 200), min_dpi=150)
    assert p.trim_w == 100 and p.min_dpi == 150


@pytest.mark.parametrize("url,status,ltype", [
    ("https://www.canva.com/design/DAGk2Lm9XyZ/Ab3dEfGh/edit", "OK", "edit"),
    ("https://www.canva.com/design/DAGk2Lm9XyZ/Ab3dEfGh/view?utm_source=x", "OSTRZEŻENIA", "view"),
    ("canva.com/design/DAGk2Lm9XyZ/view", "OSTRZEŻENIA", "view"),
    ("https://www.canva.com/templates/EAF123/", "BŁĘDY", "template"),
    ("https://canva.link/abc", "DO_WERYFIKACJI", "short"),
    ("https://example.com/design/DAG", "BŁĘDY", None),
])
def test_canva_links(url, status, ltype):
    res = canva_link.parse_canva_link(url)
    assert res["link_type"] == ltype
    assert M.overall_status(res["findings"]) == status


def test_canva_checklist_folded_product():
    items = canva_link.client_checklist(M.get_product(RULES, "ulotka_a4_skladana_dl"), RULES)
    assert any("rozkładówka" in s for s in items)
    assert any("297×210" in s for s in items)
