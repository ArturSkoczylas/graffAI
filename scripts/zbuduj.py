#!/usr/bin/env python3
"""Buduje artefakty skilla „odpowiedzi-klientom”.

  python scripts/zbuduj.py            # indeks w SKILL.md + demo/demo.html + dist/odpowiedzi-klientom.zip
  python scripts/zbuduj.py --prompt   # wypisz pełny prompt (np. do wklejenia w Claude / API)
  python scripts/zbuduj.py --check    # tylko sprawdź, czy indeks w SKILL.md jest aktualny (exit 1 gdy nie)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import odpowiedzi as O  # noqa: E402

START, END = "<!-- INDEKS:START", "<!-- INDEKS:END -->"


def render_skill_md(text: str, index: str) -> str:
    pat = re.compile(re.escape(START) + r".*?-->.*?" + re.escape(END), re.S)
    block = (START + " (generowany przez scripts/zbuduj.py – nie edytuj ręcznie) -->\n"
             + index + "\n" + END)
    if not pat.search(text):
        raise SystemExit("Brak znaczników INDEKS w SKILL.md")
    return pat.sub(lambda _: block, text)


def build_demo(out: Path) -> None:
    src = (O.ROOT / "demo" / "szablon.html").read_text(encoding="utf-8")
    templates = O.load_templates()
    data = {
        "prompt": O.build_prompt(),
        "przypadki": O.load_cases(),
        "szablony": [{k: t.get(k) for k in ("id", "tytul", "kategoria", "tryb", "kiedy", "body")}
                     for t in templates],
        "dozwoloneKwoty": sorted(O.allowed_amounts()),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    if "/*__DANE__*/null" not in src:
        raise SystemExit("Brak znacznika /*__DANE__*/null w demo/szablon.html")
    out.write_text(src.replace("/*__DANE__*/null", payload), encoding="utf-8")


def build_zip(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(O.SKILL.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, Path("odpowiedzi-klientom") / p.relative_to(O.SKILL))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    skill_md = O.SKILL / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    new = render_skill_md(text, O.template_index(O.load_templates()))
    if a.check:
        if new != text:
            print("Indeks w SKILL.md jest nieaktualny – uruchom: python scripts/zbuduj.py")
            return 1
        print("Indeks aktualny.")
        return 0
    if a.prompt:
        print(O.build_prompt(json_mode=False))
        return 0

    if new != text:
        skill_md.write_text(new, encoding="utf-8")
        print("Zaktualizowano indeks w SKILL.md")
    build_demo(O.ROOT / "demo" / "demo.html")
    build_zip(O.ROOT / "dist" / "odpowiedzi-klientom.zip")
    print("Zbudowano demo/demo.html i dist/odpowiedzi-klientom.zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
