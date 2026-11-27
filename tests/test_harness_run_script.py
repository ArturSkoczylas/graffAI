"""Tests for harness/run_script.py - running skill scripts (subprocess, argv, no shell)."""
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.agent import run_script as RS  # noqa: E402
from harness.src.agent.providers.base import ToolCall  # noqa: E402
from harness.src.agent.skills_registry import SKILLS_ROOT  # noqa: E402

_PROBE_SOURCE = textwrap.dedent("""
    import sys
    import time
    from pathlib import Path

    args = sys.argv[1:]
    if "--sleep" in args:
        time.sleep(2)
    elif "--big" in args:
        print("x" * 5000)
    elif "--fail" in args:
        print("stdout przed porażką")
        sys.stderr.write("boom\\n")
        sys.exit(7)
    else:
        print("ARGV:" + "|".join(args))
        if args and not args[0].startswith("--"):
            print("FILECONTENT:" + Path(args[0]).read_text(encoding="utf-8"))
""")


@pytest.fixture
def probe_root(tmp_path, monkeypatch):
    script_dir = tmp_path / "testskill" / "scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "probe.py").write_text(_PROBE_SOURCE, encoding="utf-8")
    monkeypatch.setattr(RS, "_ENTRYPOINTS", {"testskill": ["probe.py"]})
    return tmp_path


def _call(**raw_input) -> ToolCall:
    return ToolCall(id="c1", name="run_skill_script", raw_input=raw_input)


# --------------------------------------------------------------------------- real entrypoint config
def test_real_entrypoints_point_to_existing_files():
    for skill, scripts in RS._ENTRYPOINTS.items():
        for script in scripts:
            assert (SKILLS_ROOT / skill / "scripts" / script).is_file()


def test_build_run_skill_script_tool_schema_enum_matches_entrypoints():
    tool = RS.build_run_skill_script_tool()
    assert set(tool.input_schema["properties"]["skill"]["enum"]) == set(RS._ENTRYPOINTS)


# --------------------------------------------------------------------------- executor: happy paths
def test_executor_args_only_happy_path(probe_root):
    executor = RS.make_run_skill_script_executor(probe_root)
    result = executor(_call(skill="testskill", script="probe.py", args=["--flag", "value"]))
    assert result.strip() == "ARGV:--flag|value"


def test_executor_input_text_becomes_leading_positional_file(probe_root):
    executor = RS.make_run_skill_script_executor(probe_root)
    result = executor(_call(skill="testskill", script="probe.py", input_text="zamowienie json", args=["--x"]))
    assert "FILECONTENT:zamowienie json" in result
    assert "--x" in result


def test_executor_temp_file_deleted_after_run(probe_root):
    executor = RS.make_run_skill_script_executor(probe_root)
    result = executor(_call(skill="testskill", script="probe.py", input_text="dane"))
    path_str = result.splitlines()[0].split("ARGV:", 1)[1]
    assert not Path(path_str).exists()


# --------------------------------------------------------------------------- executor: invalid input
def test_executor_unknown_skill_returns_friendly_error_not_raising(probe_root):
    executor = RS.make_run_skill_script_executor(probe_root)
    result = executor(_call(skill="nope", script="probe.py"))
    assert "Nieznany skrypt" in result


def test_executor_unknown_script_for_known_skill_returns_friendly_error(probe_root):
    executor = RS.make_run_skill_script_executor(probe_root)
    result = executor(_call(skill="testskill", script="evil.py"))
    assert "Nieznany skrypt" in result
    assert "evil.py" in result


def test_executor_missing_script_file_on_disk_returns_message(tmp_path, monkeypatch):
    monkeypatch.setattr(RS, "_ENTRYPOINTS", {"testskill": ["ghost.py"]})
    (tmp_path / "testskill" / "scripts").mkdir(parents=True)
    executor = RS.make_run_skill_script_executor(tmp_path)
    result = executor(_call(skill="testskill", script="ghost.py"))
    assert "nie istnieje" in result


def test_executor_malformed_args_missing_script_raises_validation_error(probe_root):
    executor = RS.make_run_skill_script_executor(probe_root)
    with pytest.raises(ValidationError):
        executor(_call(skill="testskill"))


# --------------------------------------------------------------------------- executor: edge behaviour
def test_executor_nonzero_exit_code_reported_in_output(probe_root):
    executor = RS.make_run_skill_script_executor(probe_root)
    result = executor(_call(skill="testskill", script="probe.py", args=["--fail"]))
    assert "stdout przed porażką" in result
    assert "boom" in result
    assert "kod wyjścia: 7" in result


def test_executor_timeout_returns_message_not_raising(probe_root, monkeypatch):
    monkeypatch.setattr(RS, "TIMEOUT_SECONDS", 0.2)
    executor = RS.make_run_skill_script_executor(probe_root)
    result = executor(_call(skill="testskill", script="probe.py", args=["--sleep"]))
    assert "Przekroczono limit czasu" in result


def test_executor_output_truncated_when_too_long(probe_root, monkeypatch):
    monkeypatch.setattr(RS, "MAX_OUTPUT_CHARS", 100)
    executor = RS.make_run_skill_script_executor(probe_root)
    result = executor(_call(skill="testskill", script="probe.py", args=["--big"]))
    assert len(result) < 200
    assert "przycięto" in result
