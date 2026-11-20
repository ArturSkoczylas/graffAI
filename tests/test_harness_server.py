"""Testy harness/api/server.py – żądanie POST /draft: surowy e-mail -> szkic w Szkicach."""
import logging
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.api import server as SRV  # noqa: E402
from harness.src.agent.agent_loop import AgentDidNotActError  # noqa: E402
from harness.src.agent.providers.base import ToolCall  # noqa: E402
from harness.src.config import Config  # noqa: E402


def _cfg(**overrides):
    base = dict(
        imap_host="imap.example.com", imap_port=993, imap_user="biuro@example.com",
        imap_password="tajne", imap_use_ssl=True, drafts_folder="Drafts",
        ai_provider="claude", ai_model="claude-sonnet-5-5", ai_api_key="sk-test",
        ai_max_tokens=3000, from_address="biuro@example.com",
        api_host="127.0.0.1", api_port=8765,
    )
    base.update(overrides)
    return Config(**base)


def _raw_email(body="treść", message_id="<a@x>"):
    msg = EmailMessage()
    msg["From"] = "klient@example.com"
    msg["Subject"] = "Pytanie"
    if message_id is not None:
        msg["Message-ID"] = message_id
    msg.set_content(body)
    return msg.as_bytes()


def _good_tool_call():
    return ToolCall(id="c1", name="create_draft",
                     raw_input={"subject": "x", "body": "Dzień dobry", "needs_human": False, "staff_notes": ""})


class _FakeImapClient:
    def logout(self) -> None:
        pass


def _wire_happy_defaults(monkeypatch, appended, client=None):
    monkeypatch.setattr(SRV.skill_prompt, "build_system_prompt",
                         lambda has_attachments=False: "SYSTEM")
    monkeypatch.setattr(SRV.skill_prompt, "build_user_message",
                         lambda body, attachment_filenames=None: f"wrapped:{body}")
    monkeypatch.setattr(SRV.providers, "get_provider", lambda *a, **kw: "FAKE_PROVIDER")
    monkeypatch.setattr(SRV, "run_agent", lambda *a, **kw: _good_tool_call())
    monkeypatch.setattr(SRV.mailbox, "connect", lambda cfg: client if client is not None else _FakeImapClient())
    monkeypatch.setattr(SRV.mailbox, "append_draft",
                         lambda c, folder, raw: appended.append((folder, raw)))


# --------------------------------------------------------------------------- create_draft_from_raw_email
def test_create_draft_happy_path(monkeypatch):
    appended = []
    _wire_happy_defaults(monkeypatch, appended)

    decision = SRV.create_draft_from_raw_email(_cfg(), _raw_email())

    assert decision.subject == "x"
    assert appended[0][0] == "Drafts"


def test_create_draft_logs_out_even_on_append_failure(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.logged_out = False

        def logout(self):
            self.logged_out = True

    client = FakeClient()
    _wire_happy_defaults(monkeypatch, [], client=client)

    def boom(c, folder, raw):
        raise ConnectionError("APPEND nie powiodło się")

    monkeypatch.setattr(SRV.mailbox, "append_draft", boom)

    with pytest.raises(ConnectionError):
        SRV.create_draft_from_raw_email(_cfg(), _raw_email())
    assert client.logged_out is True


def test_create_draft_garbage_bytes_still_parses(monkeypatch):
    # email.message_from_bytes nigdy nie podnosi wyjątku, nawet dla śmieci – zwraca
    # wiadomość bez sensownych nagłówków/treści, więc dalszy przepływ i tak ruszy.
    appended = []
    _wire_happy_defaults(monkeypatch, appended)

    decision = SRV.create_draft_from_raw_email(_cfg(), b"to nie jest poprawny e-mail")

    assert decision.subject == "x"


def test_create_draft_run_agent_failure_propagates(monkeypatch):
    _wire_happy_defaults(monkeypatch, [])

    def flaky(*a, **kw):
        raise AgentDidNotActError("model się nie odezwał")

    monkeypatch.setattr(SRV, "run_agent", flaky)

    with pytest.raises(AgentDidNotActError):
        SRV.create_draft_from_raw_email(_cfg(), _raw_email())


def test_create_draft_malformed_tool_input_raises(monkeypatch):
    _wire_happy_defaults(monkeypatch, [])
    monkeypatch.setattr(SRV, "run_agent", lambda *a, **kw: ToolCall(
        id="c", name="create_draft", raw_input={"subject": "x"}  # brak wymaganych pól
    ))

    with pytest.raises(Exception):
        SRV.create_draft_from_raw_email(_cfg(), _raw_email())


def test_create_draft_no_attachments_does_not_offer_check_print_file_tool(monkeypatch):
    _wire_happy_defaults(monkeypatch, [])
    seen_tools = []
    monkeypatch.setattr(SRV, "run_agent",
                         lambda provider, system, user_message, tools, stop_tool, executors=None:
                         (seen_tools.append((tools, executors)), _good_tool_call())[1])

    SRV.create_draft_from_raw_email(_cfg(), _raw_email())

    tools, executors = seen_tools[0]
    assert {t.name for t in tools} == {"create_draft", "read_skill", "run_skill_script"}
    assert set(executors) == {"read_skill", "run_skill_script"}


def test_create_draft_with_attachment_offers_check_print_file_tool(monkeypatch):
    _wire_happy_defaults(monkeypatch, [])
    seen_tools = []
    monkeypatch.setattr(SRV, "run_agent",
                         lambda provider, system, user_message, tools, stop_tool, executors=None:
                         (seen_tools.append((tools, executors)), _good_tool_call())[1])

    msg = EmailMessage()
    msg["From"] = "klient@example.com"
    msg["Subject"] = "Projekt do druku"
    msg.set_content("W załączniku plik.")
    msg.add_attachment(b"%PDF-1.7 fake", maintype="application", subtype="pdf", filename="projekt.pdf")

    SRV.create_draft_from_raw_email(_cfg(), msg.as_bytes())

    tools, executors = seen_tools[0]
    assert {t.name for t in tools} == {"create_draft", "read_skill", "run_skill_script", "check_print_file"}
    assert "check_print_file" in executors


def test_create_draft_connect_failure_propagates(monkeypatch):
    _wire_happy_defaults(monkeypatch, [])

    def boom(cfg):
        raise ConnectionError("nie udało się połączyć z IMAP")

    monkeypatch.setattr(SRV.mailbox, "connect", boom)

    with pytest.raises(ConnectionError):
        SRV.create_draft_from_raw_email(_cfg(), _raw_email())


# --------------------------------------------------------------------------- handle_draft_request
def test_handle_draft_request_happy_returns_200(monkeypatch):
    _wire_happy_defaults(monkeypatch, [])
    status, payload = SRV.handle_draft_request(_cfg(), _raw_email())
    assert status == 200
    assert payload == {"status": "ok", "subject": "x", "needs_human": False}


def test_handle_draft_request_empty_body_returns_400():
    status, payload = SRV.handle_draft_request(_cfg(), b"")
    assert status == 400
    assert payload["status"] == "error"


def test_handle_draft_request_internal_failure_returns_500_not_raises(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="harness.api")
    _wire_happy_defaults(monkeypatch, [])
    monkeypatch.setattr(SRV, "run_agent", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("padło")))

    status, payload = SRV.handle_draft_request(_cfg(), _raw_email())

    assert status == 500
    assert payload == {"status": "error", "message": "padło"}
    assert len(caplog.records) >= 1
