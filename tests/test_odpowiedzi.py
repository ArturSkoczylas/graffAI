"""Testy offline skilla „odpowiedzi-klientom” – bez wywoływania modelu.

Sprawdzają, że szablony, fakty i przypadki testowe są spójne, oraz że automatyczna ocena
(używana w demo i w scripts/uruchom_evale.py) działa poprawnie.
"""
import re
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import odpowiedzi as O  # noqa: E402
import zbuduj  # noqa: E402

TEMPLATES = O.load_templates()
IDS = {t["id"] for t in TEMPLATES}
CASES = O.load_cases()
FACTS = O.load_facts()


# --------------------------------------------------------------------------- szablony
@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["id"])
def test_template_structure(t):
    for key in ("id", "tytul", "kategoria", "tryb", "kiedy", "zrodlo"):
        assert t.get(key), f"{t['plik']}: brak pola {key}"
    assert t["plik"] == f"{t['id']}.md"
    assert t["tryb"] in ("klient", "pracownik")
    assert len(t["body"]) > 40


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["id"])
def test_template_variables_declared(t):
    used = set(O.VAR_RE.findall(t["body"]))
    declared = set((t.get("zmienne") or {}).keys())
    assert used == declared, f"{t['id']}: w treści {used}, zadeklarowane {declared}"


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["id"])
def test_no_bank_account_outside_transfer_template(t):
    if t["id"] != "dane-do-przelewu":
        assert not O.NRB_RE.search(t["body"])


def test_ids_unique():
    assert len(IDS) == len(TEMPLATES)


def test_staff_templates_marked():
    for tid in ("gotowe-zamowienie-odbior", "gotowe-zamowienie-wysylka", "dane-do-przelewu",
                "minima-logistyczne", "wizualizacja-obrazu"):
        assert next(t for t in TEMPLATES if t["id"] == tid)["tryb"] == "pracownik"


def test_links_match_facts():
    """Każdy link do strony drukarni w szablonach musi być na liście linków w fakty.yaml."""
    known = set(FACTS["linki"].values()) | {FACTS["firma"]["opinie_google"]}
    for t in TEMPLATES:
        for url in re.findall(r"https://gutenberg-drukarnia\.pl/[^\s)]*", t["body"]):
            assert url.rstrip(".,") in known, f"{t['id']}: nieznany link {url}"


# --------------------------------------------------------------------------- SKILL.md
def test_skill_index_up_to_date():
    text = (O.SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert zbuduj.render_skill_md(text, O.template_index(TEMPLATES)) == text, \
        "Uruchom: python scripts/zbuduj.py"


def test_skill_frontmatter():
    fm, _ = O.split_front_matter((O.SKILL / "SKILL.md").read_text(encoding="utf-8"))
    assert fm["name"] == "odpowiedzi-klientom"
    assert 20 < len(fm["description"]) < 1024


def test_prompt_contains_everything():
    p = O.build_prompt()
    for t in TEMPLATES:
        assert f"szablon: {t['id']}" in p
    assert "Miejska 14" in p and '"szkic"' in p


def test_zip(tmp_path):
    out = tmp_path / "s.zip"
    zbuduj.build_zip(out)
    names = zipfile.ZipFile(out).namelist()
    assert "odpowiedzi-klientom/SKILL.md" in names
    assert sum(n.startswith("odpowiedzi-klientom/szablony/") for n in names) == len(TEMPLATES)


# --------------------------------------------------------------------------- przypadki testowe
def test_cases_reference_existing_templates():
    for c in CASES:
        for tid in c.get("oczekiwane_szablony") or []:
            assert tid in IDS, f"{c['id']}: nieznany szablon {tid}"


def test_cases_unique_and_complete():
    assert len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert c.get("wiadomosc", "").strip() and c.get("tytul")


def test_expected_phrases_exist_in_sources():
    """Fraza wymagana w odpowiedzi musi gdzieś występować w szablonach/faktach/wiadomości
    – inaczej test wymagałby od modelu wymyślenia czegoś."""
    corpus = O._norm(O.build_prompt())
    for c in CASES:
        src = corpus + O._norm(c["wiadomosc"]) + O._norm(c.get("notatka", ""))
        for s in c.get("musi_zawierac", []):
            assert O._norm(s) in src, f"{c['id']}: „{s}” nie występuje w źródłach"


# --------------------------------------------------------------------------- ocena
ALLOWED = O.allowed_amounts()
CASE = next(c for c in CASES if c["id"] == "wysylka-platnosc")


def _ok(checks):
    return all(ch["ok"] for ch in checks)


def test_evaluate_good_answer():
    good = {"szablony": ["platnosc-i-realizacja"], "wymaga_czlowieka": False,
            "szkic": "Dzień dobry,\n\nczas realizacji to 3-4 dni robocze. Wysyłka kosztuje 20 zł, "
                     "powyżej 500 zł gratis; przy wysyłce płatność z góry.\n\nPozdrawiam"}
    checks = O.evaluate(CASE, good, ALLOWED)
    assert _ok(checks), [c for c in checks if not c["ok"]]


def test_evaluate_catches_invented_price():
    bad = {"szablony": ["platnosc-i-realizacja"], "wymaga_czlowieka": False,
           "szkic": "Dzień dobry, 3-4 dni, z góry, wysyłka 20 zł, gratis od 500 zł, "
                    "a ulotki kosztują 237 zł."}
    failed = [c["nazwa"] for c in O.evaluate(CASE, bad, ALLOWED) if not c["ok"]]
    assert failed == ["Tylko kwoty z szablonów / faktów"]


def test_evaluate_catches_wrong_template_and_leftovers():
    bad = {"szablony": ["tapety"], "wymaga_czlowieka": True,
           "szkic": "Witam, do zapłaty {{kwota}}. Konto 89 1090 2402 0000"}
    failed = {c["nazwa"] for c in O.evaluate(CASE, bad, ALLOWED) if not c["ok"]}
    assert {"Dobrany szablon", "Flaga „wymaga człowieka”", "Zaczyna się od „Dzień dobry”",
            "Brak niewypełnionych {{zmiennych}}", "Brak numeru konta"} <= failed


def test_parse_json_reply_variants():
    assert O.parse_json_reply('{"a": 1}') == {"a": 1}
    assert O.parse_json_reply('Oto wynik:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert O.parse_json_reply('Wynik: {"a": 3} koniec') == {"a": 3}
    with pytest.raises(ValueError):
        O.parse_json_reply("brak jsona")
