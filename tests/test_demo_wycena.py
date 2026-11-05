"""Zakładka „Wycena” w demo (demo/wycena.js budowane przez scripts/zbuduj.py)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_demo_quote_tab_has_skill_and_cases():
    """Zakładka „Wycena” w demo: prompt z SKILL.md skilla wycena i przykłady z evals/wycena.yaml."""
    import yaml
    sys.path.insert(0, str(ROOT / "scripts"))
    import zbuduj
    js = zbuduj.quote_js()
    assert "/*__WYCENA__*/" not in js and "</script" not in js.lower()
    data, _ = json.JSONDecoder().raw_decode(js, js.index("const D = ") + 10)
    assert "Krok 5. Zapisz plik zamówienia i wyceń" in data["prompt"]
    assert "name: wycena" not in data["prompt"]                      # bez frontmattera
    cases = yaml.safe_load((ROOT / "evals/wycena.yaml").read_text(encoding="utf-8"))["przypadki"]
    assert [c["id"] for c in data["przypadki"]] == [c["id"] for c in cases]
    assert all("wzorzec" not in c for c in data["przypadki"])        # wzorcowa ekstrakcja nie trafia do strony
