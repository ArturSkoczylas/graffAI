"""Testy harness/skills_registry.py – odkrywanie skilli i wczytywanie ich na żądanie."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.agent import skills_registry as R  # noqa: E402

ALL_SKILLS = {"odpowiedzi-klientom", "pdf-check", "margin-check", "wycena"}


# --------------------------------------------------------------------------- discover_skills
def test_discover_skills_finds_all_real_skills():
    skills = R.discover_skills()
    assert {s.name for s in skills} == ALL_SKILLS


def test_discover_skills_captures_description():
    skills = {s.name: s for s in R.discover_skills()}
    assert "Drukarni Gutenberg" in skills["pdf-check"].description


def test_discover_skills_empty_root_returns_empty_list(tmp_path):
    assert R.discover_skills(tmp_path) == []


# --------------------------------------------------------------------------- render_available_skills
def test_render_available_skills_lists_all_names_and_descriptions():
    rendered = R.render_available_skills(R.discover_skills())
    assert rendered.startswith("<available_skills>")
    assert rendered.endswith("</available_skills>")
    for name in ALL_SKILLS:
        assert name in rendered


def test_render_available_skills_empty_list():
    rendered = R.render_available_skills([])
    assert rendered == "<available_skills>\n</available_skills>"


# --------------------------------------------------------------------------- read_skill
def test_read_skill_odpowiedzi_klientom_includes_templates_and_facts():
    body = R.read_skill("odpowiedzi-klientom")
    assert "fakty.yaml" in body
    assert "szablon:" in body


def test_read_skill_pdf_check_returns_body_without_frontmatter():
    body = R.read_skill("pdf-check")
    assert not body.startswith("---")
    assert "spady" in body.lower()


def test_read_skill_pdf_check_includes_harness_adaptation_note():
    body = R.read_skill("pdf-check")
    assert "check_print_file" in body
    assert "needs_human" in body


def test_read_skill_wycena_includes_harness_adaptation_note():
    body = R.read_skill("wycena")
    assert "needs_human" in body
    assert "run_skill_script" in body


def test_read_skill_unknown_name_raises_key_error_listing_available():
    with pytest.raises(KeyError) as exc_info:
        R.read_skill("nope")
    assert "pdf-check" in str(exc_info.value)


# --------------------------------------------------------------------------- read_skill tool
def test_build_read_skill_tool_schema_enum_matches_discovered_skills():
    tool = R.build_read_skill_tool()
    assert set(tool.input_schema["properties"]["name"]["enum"]) == ALL_SKILLS


# --------------------------------------------------------------------------- executor
def test_read_skill_executor_happy_path_returns_body():
    executor = R.make_read_skill_executor()
    call = R.ToolCall(id="c1", name="read_skill", raw_input={"name": "margin-check"})
    assert "spady" in executor(call).lower()


def test_read_skill_executor_unknown_name_returns_friendly_error_not_raising():
    executor = R.make_read_skill_executor()
    call = R.ToolCall(id="c1", name="read_skill", raw_input={"name": "nope"})
    result = executor(call)
    assert "Nieznany skill" in result
