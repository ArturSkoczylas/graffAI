#!/usr/bin/env python3
"""Uruchamia przypadki testowe skilla „odpowiedzi-klientom” na prawdziwym modelu (Claude API).

Wymaga klucza API:  export ANTHROPIC_API_KEY=...   oraz   pip install anthropic

  python scripts/uruchom_evale.py                      # wszystkie przypadki
  python scripts/uruchom_evale.py --tylko reklamacja   # wybrane (id lub fragment id)
  python scripts/uruchom_evale.py --model claude-sonnet-5-5 --raport evals/wyniki.md

Bez klucza API to samo zobaczysz w demo (demo/demo.html opublikowane jako artefakt w Claude).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import odpowiedzi as O  # noqa: E402


def ask(client, model: str, request: str) -> tuple[dict, float]:
    t0 = time.time()
    msg = client.messages.create(model=model, max_tokens=3000,
                                 messages=[{"role": "user", "content": request}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return O.parse_json_reply(text), time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("GRAFFAI_MODEL", "claude-sonnet-5-5"))
    ap.add_argument("--tylko", nargs="*", help="id przypadków (lub ich fragmenty)")
    ap.add_argument("--raport", type=Path, default=Path("evals/wyniki.md"))
    a = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Brak ANTHROPIC_API_KEY. Ustaw klucz albo użyj demo (demo/demo.html).", file=sys.stderr)
        return 3
    try:
        import anthropic
    except ImportError:
        print("Zainstaluj bibliotekę: pip install anthropic", file=sys.stderr)
        return 3

    client = anthropic.Anthropic()
    prompt = O.build_prompt()
    allowed = O.allowed_amounts()
    cases = O.load_cases()
    if a.tylko:
        cases = [c for c in cases if any(s in c["id"] for s in a.tylko)]

    lines = [f"# Wyniki testów – odpowiedzi-klientom\n\nModel: `{a.model}`\n"]
    passed = 0
    for c in cases:
        print(f"→ {c['id']} … ", end="", flush=True)
        try:
            result, secs = ask(client, a.model,
                               O.build_request(prompt, c["wiadomosc"], c.get("notatka", "")))
            checks = O.evaluate(c, result, allowed)
        except Exception as exc:  # noqa: BLE001
            print(f"BŁĄD: {exc}")
            lines.append(f"## ✖ {c['tytul']} (`{c['id']}`)\n\nBłąd: {exc}\n")
            continue
        ok = all(ch["ok"] for ch in checks)
        passed += ok
        print(("OK" if ok else "NIE") + f" ({secs:.0f} s)")
        lines.append(f"## {'✔' if ok else '✖'} {c['tytul']} (`{c['id']}`)\n")
        lines.append("**Wiadomość:**\n\n> " + c["wiadomosc"].strip().replace("\n", "\n> ") + "\n")
        for ch in checks:
            lines.append(f"- {'✔' if ch['ok'] else '✖'} {ch['nazwa']}"
                         + (f" – {ch['szczegoly']}" if ch["szczegoly"] else ""))
        lines.append("\n**Szablony:** " + ", ".join(result.get("szablony") or ["–"]))
        lines.append("\n**Szkic:**\n\n```\n" + result.get("szkic", "") + "\n```")
        if result.get("uwagi"):
            lines.append("\n**Uwagi:** " + "; ".join(result["uwagi"]))
        lines.append("")

    summary = f"\n**Wynik: {passed}/{len(cases)} przypadków zaliczonych.**\n"
    lines.insert(1, summary)
    a.raport.parent.mkdir(parents=True, exist_ok=True)
    a.raport.write_text("\n".join(lines), encoding="utf-8")
    print(summary.strip("\n*"), f"– raport: {a.raport}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
