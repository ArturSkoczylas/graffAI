from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .providers.base import ToolCall, ToolSpec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SKILLS_ROOT = REPO_ROOT / "skills"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import odpowiedzi as _O  # noqa: E402

_ADAPTATIONS: dict[str, str] = {
    "pdf-check": (
        "\n\n## Jak to działa w tym środowisku (harness)\n\n"
        "Nie masz tu Bash ani Read – nie uruchamiasz skryptów i nie widzisz podglądu. Jedyne "
        "narzędzie to `check_print_file`. Przy wyniku SPRAWDŹ lub OSTRZEŻENIE ustaw w "
        "`create_draft` `needs_human=true` i wypisz konkretne znaleziska w `staff_notes` – "
        "podgląd musi obejrzeć pracownik, Ty nie możesz go ocenić wzrokowo."
    ),
    "margin-check": (
        "\n\n## Jak to działa w tym środowisku (harness)\n\n"
        "Nie masz tu Bash ani Read, więc nie widzisz podglądu – dla załączonych plików "
        "(JPG/PNG/TIFF) jedyne narzędzie to `check_print_file`. Przy wyniku SPRAWDŹ lub "
        "OSTRZEŻENIE ustaw w `create_draft` `needs_human=true` i wypisz konkretne znaleziska w "
        "`staff_notes` – podgląd musi obejrzeć pracownik, Ty nie możesz go ocenić wzrokowo.\n\n"
        "Dla **linków do Canvy** (nie plików) użyj `run_skill_script(skill=\"margin-check\", "
        "script=\"canva_link.py\", args=[url, \"--product\", <id>, \"--json\"])`."
    ),
    "wycena": (
        "\n\n## Jak to działa w tym środowisku (harness)\n\n"
        "Wywołaj `run_skill_script(skill=\"wycena\", script=\"wycena.py\", args=[\"--papers\"])`, "
        "żeby najpierw sprawdzić dokładne nazwy papierów. Zbuduj zamówienie wg powyższych tabel "
        "jako JSON, podaj go w `input_text` (treść pliku, który normalnie byłby argumentem "
        "`plik`) i wywołaj ponownie z `args=[\"--json\"]`, żeby dostać wynik w formacie "
        "strukturalnym. **Nigdy nie licz ceny sam** – to, co zwróci skrypt, jest jedynym "
        "źródłem ceny. Jeśli wynik jest częściowy (brak ceny, pytania do klienta, książki bez "
        "wyceny) albo skrypt zwróci błąd, ustaw w `create_draft` `needs_human=true` i opisz to "
        "w `staff_notes`."
    ),
}


def strip_front_matter(text: str) -> str:
    return _O.split_front_matter(text)[1]


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: Path


def discover_skills(root: Path = SKILLS_ROOT) -> list[SkillMeta]:
    out = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        front, _ = _O.split_front_matter(skill_md.read_text(encoding="utf-8"))
        out.append(SkillMeta(name=front["name"], description=front["description"], path=skill_md))
    return out


def render_available_skills(skills: list[SkillMeta]) -> str:
    lines = ["<available_skills>"]
    for s in sorted(skills, key=lambda s: s.name):
        lines.append(f"- {s.name}: {s.description}")
    lines.append("</available_skills>")
    return "\n".join(lines)


def read_skill(name: str, root: Path = SKILLS_ROOT) -> str:
    if name == "odpowiedzi-klientom":
        return _O.build_prompt(json_mode=False)

    by_name = {s.name: s for s in discover_skills(root)}
    skill = by_name.get(name)
    if skill is None:
        available = ", ".join(sorted(by_name)) or "(brak skilli)"
        raise KeyError(f"Nieznany skill {name!r}. Dostępne: {available}.")

    body = strip_front_matter(skill.path.read_text(encoding="utf-8"))
    return body + _ADAPTATIONS.get(name, "")


def build_read_skill_tool(root: Path = SKILLS_ROOT) -> ToolSpec:
    names = sorted(s.name for s in discover_skills(root))
    return ToolSpec(
        name="read_skill",
        description=(
            "Wczytaj pełną instrukcję (SKILL.md i powiązane materiały) jednego ze skilli "
            "drukarni, zanim zaczniesz stosować jego reguły."
        ),
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string", "enum": names}},
            "required": ["name"],
        },
    )


def make_read_skill_executor(root: Path = SKILLS_ROOT) -> Callable[[ToolCall], str]:
    def executor(call: ToolCall) -> str:
        try:
            return read_skill(call.raw_input["name"], root)
        except KeyError as exc:
            return str(exc)

    return executor
