"""Tests for harness/main.py - process entry point: building Config + starting the HTTP server."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src import main as MAIN  # noqa: E402

REQUIRED_ENV = {
    "IMAP_HOST": "imap.example.com",
    "IMAP_USER": "biuro@example.com",
    "IMAP_PASSWORD": "tajne",
    "AI_API_KEY": "sk-test",
}


def test_main_happy_path_runs_server(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    calls = []
    monkeypatch.setattr(MAIN.server, "run", lambda cfg: calls.append(cfg))

    exit_code = MAIN.main()

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0].imap_host == "imap.example.com"


def test_main_missing_required_env_returns_nonzero_without_traceback(monkeypatch, capsys):
    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.delenv("IMAP_USER", raising=False)
    monkeypatch.delenv("IMAP_PASSWORD", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setattr(MAIN.server, "run", lambda cfg: (_ for _ in ()).throw(
        AssertionError("server.run should not be called")
    ))

    exit_code = MAIN.main()

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "Configuration error" in err
