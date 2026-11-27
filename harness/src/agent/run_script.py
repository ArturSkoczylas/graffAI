from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict

from .providers.base import ToolCall, ToolSpec
from .skills_registry import SKILLS_ROOT

TIMEOUT_SECONDS = 45
MAX_OUTPUT_CHARS = 20_000

# Only scripts that take plain text/URL as input (not a binary client file - that's
# handled by check_print_file, directly on the attachment bytes, without this tool).
_ENTRYPOINTS: dict[str, list[str]] = {
    "wycena": ["wycena.py"],
    "margin-check": ["canva_link.py"],
}


class RunSkillScriptArgs(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill: str
    script: str
    args: list[str] = []
    input_text: Optional[str] = None


def _tool_description() -> str:
    entries = "\n".join(f"- {skill}: {', '.join(scripts)}" for skill, scripts in sorted(_ENTRYPOINTS.items()))
    return (
        "Uruchom skrypt skilla (Python) i zwróć jego wyjście (stdout/stderr/kod wyjścia). "
        "Tylko dla skryptów biorących tekst/URL, nie pliki binarne klienta – te sprawdza "
        "`check_print_file`. Dostępne:\n" + entries + "\n\n"
        "`args` to flagi z linii komend (np. [\"--product\", \"ulotka_a5\", \"--json\"]). Jeśli "
        "skrypt wymaga pliku jako pierwszego argumentu pozycyjnego (np. `wycena.py` – JSON "
        "zamówienia), podaj jego treść w `input_text` – zostanie zapisana do pliku tymczasowego, "
        "którego ścieżkę dostanie jako pierwszy argument, przed `args`."
    )


def build_run_skill_script_tool() -> ToolSpec:
    return ToolSpec(
        name="run_skill_script",
        description=_tool_description(),
        input_schema={
            "type": "object",
            "properties": {
                "skill": {"type": "string", "enum": sorted(_ENTRYPOINTS)},
                "script": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
                "input_text": {"type": ["string", "null"]},
            },
            "required": ["skill", "script"],
        },
    )


def make_run_skill_script_executor(root: Path = SKILLS_ROOT) -> Callable[[ToolCall], str]:
    def executor(call: ToolCall) -> str:
        parsed = RunSkillScriptArgs.model_validate(call.raw_input)

        allowed = _ENTRYPOINTS.get(parsed.skill, [])
        if parsed.script not in allowed:
            return (
                f"Nieznany skrypt {parsed.script!r} dla skilla {parsed.skill!r}. "
                f"Dostępne: {', '.join(allowed) or '(brak)'}."
            )

        script_path = root / parsed.skill / "scripts" / parsed.script
        if not script_path.is_file():
            return f"Skrypt {script_path} nie istnieje."

        argv = [sys.executable, str(script_path)]
        tmp_path: Optional[Path] = None
        try:
            if parsed.input_text is not None:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, encoding="utf-8",
                ) as tmp:
                    tmp.write(parsed.input_text)
                    tmp_path = Path(tmp.name)
                argv.append(str(tmp_path))
            argv.extend(parsed.args)

            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                return f"Przekroczono limit czasu ({TIMEOUT_SECONDS}s) dla {parsed.script}."

            output = proc.stdout
            if proc.stderr:
                output += f"\n--- stderr ---\n{proc.stderr}"
            if proc.returncode != 0:
                output += f"\n--- kod wyjścia: {proc.returncode} ---"
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n... (przycięto)"
            return output
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    return executor
