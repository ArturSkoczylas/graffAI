"""Testy harness/watcher.py – handle_new_mail (okablowanie + granice błędów) i run (routing)."""
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.mail_listener import watcher as W  # noqa: E402
from harness.src.agent.agent_loop import AgentDidNotActError  # noqa: E402
from harness.src.config import Config  # noqa: E402
from harness.src.mail_listener.mailbox import FetchedMessage, FolderInfo  # noqa: E402
from harness.src.agent.providers.base import ToolCall  # noqa: E402
from harness.src.mail_listener.state import ProcessedState  # noqa: E402


def _cfg(**overrides):
    base = dict(
        imap_host="imap.example.com", imap_port=993, imap_user="biuro@example.com",
        imap_password="tajne", imap_use_ssl=True, inbox_folder="INBOX", drafts_folder="Drafts",
        detection_mode="idle", poll_interval_seconds=60, use_skill=True,
        ai_provider="claude", ai_model="claude-sonnet-5-5", ai_api_key="sk-test",
        ai_max_tokens=3000, state_file="/tmp/state.json", from_address="biuro@example.com",
    )
    base.update(overrides)
    return Config(**base)


def _baseline_state(last_uid=0, uid_validity=7):
    return ProcessedState().with_baseline(last_uid=last_uid, uid_validity=uid_validity)


def _msg(uid, message_id, plain_text="treść"):
    return FetchedMessage(uid=uid, message_id=message_id, plain_text=plain_text, original=object())


def _good_tool_call():
    return ToolCall(id="c1", name="create_draft",
                     raw_input={"subject": "Re: x", "body": "Dzień dobry", "needs_human": False, "staff_notes": ""})


def _wire_happy_defaults(monkeypatch, fetched, uid_validity=7, uid_next=99):
    monkeypatch.setattr(W.mailbox, "select_folder",
                         lambda client, folder: FolderInfo(uid_validity=uid_validity, uid_next=uid_next))
    monkeypatch.setattr(W.mailbox, "fetch_new", lambda client, since_uid: fetched)
    monkeypatch.setattr(W.skill_prompt, "build_system_prompt", lambda use_skill: "SYSTEM")
    monkeypatch.setattr(W.skill_prompt, "build_user_message", lambda body: f"wrapped:{body}")
    monkeypatch.setattr(W.providers, "get_provider", lambda *a, **kw: "FAKE_PROVIDER")
    monkeypatch.setattr(W, "run_agent", lambda *a, **kw: _good_tool_call())
    monkeypatch.setattr(W.mailbox, "build_draft_mime", lambda original, from_addr, decision: b"RAW")
    monkeypatch.setattr(ProcessedState, "save", lambda self, path: None)


# --------------------------------------------------------------------------- baseline bootstrap
def test_handle_new_mail_first_run_sets_baseline_without_processing(monkeypatch):
    monkeypatch.setattr(W.mailbox, "select_folder",
                         lambda client, folder: FolderInfo(uid_validity=7, uid_next=101))
    monkeypatch.setattr(W.mailbox, "fetch_new", lambda *a, **kw: pytest.fail("nie powinno być wywołane"))
    monkeypatch.setattr(W, "run_agent", lambda *a, **kw: pytest.fail("nie powinno być wywołane"))

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=ProcessedState())

    assert result.has_baseline() is True
    assert result.last_uid == 100
    assert result.uid_validity == 7


def test_handle_new_mail_uid_validity_change_rebaselines(monkeypatch):
    monkeypatch.setattr(W.mailbox, "select_folder",
                         lambda client, folder: FolderInfo(uid_validity=999, uid_next=51))
    monkeypatch.setattr(W.mailbox, "fetch_new", lambda *a, **kw: pytest.fail("nie powinno być wywołane"))

    old_state = _baseline_state(last_uid=1000, uid_validity=7)  # stare UID-y są już nieważne
    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=old_state)

    assert result.last_uid == 50
    assert result.uid_validity == 999


def test_handle_new_mail_same_uid_validity_does_not_rebaseline(monkeypatch):
    _wire_happy_defaults(monkeypatch, [], uid_validity=7, uid_next=99)
    state = _baseline_state(last_uid=10, uid_validity=7)

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=state)

    assert result.last_uid == 10  # brak nowych wiadomości, bez zmian


def test_handle_new_mail_select_folder_fails_aborts(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="harness.watcher")

    def boom(client, folder):
        raise ConnectionError("IMAP padł")

    monkeypatch.setattr(W.mailbox, "select_folder", boom)

    state = ProcessedState()
    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=state)

    assert result == state
    assert any("wybrać folderu" in r.message for r in caplog.records)


# --------------------------------------------------------------------------- happy path
def test_handle_new_mail_happy_one_message(monkeypatch):
    appended = []
    _wire_happy_defaults(monkeypatch, [_msg(5, "<1@x>")])
    monkeypatch.setattr(W.mailbox, "append_draft", lambda client, folder, raw: appended.append((folder, raw)))

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=_baseline_state())

    assert result.is_processed("<1@x>") is True
    assert result.last_uid == 5
    assert appended == [("Drafts", b"RAW")]


def test_handle_new_mail_skips_already_processed(monkeypatch):
    calls = []
    _wire_happy_defaults(monkeypatch, [_msg(5, "<1@x>")])
    monkeypatch.setattr(W, "run_agent", lambda *a, **kw: calls.append(1) or _good_tool_call())

    state = _baseline_state().mark_processed("<1@x>")
    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=state)

    assert calls == []
    assert result.last_uid == 5  # i tak przesuwamy znacznik, to już załatwione


def test_handle_new_mail_two_messages_both_processed(monkeypatch):
    appended = []
    _wire_happy_defaults(monkeypatch, [_msg(5, "<1@x>"), _msg(6, "<2@x>")])
    monkeypatch.setattr(W.mailbox, "append_draft", lambda client, folder, raw: appended.append(raw))

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=_baseline_state())

    assert result.is_processed("<1@x>") is True
    assert result.is_processed("<2@x>") is True
    assert result.last_uid == 6
    assert len(appended) == 2


# --------------------------------------------------------------------------- batch-level failures
def test_handle_new_mail_fetch_new_fails_aborts_batch(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="harness.watcher")
    monkeypatch.setattr(W.mailbox, "select_folder",
                         lambda client, folder: FolderInfo(uid_validity=7, uid_next=99))

    def boom(client, since_uid):
        raise ConnectionError("IMAP padł")

    monkeypatch.setattr(W.mailbox, "fetch_new", boom)
    monkeypatch.setattr(W, "run_agent", lambda *a, **kw: pytest.fail("nie powinno być wywołane"))

    state = _baseline_state()
    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=state)

    assert result == state
    assert any("cyklu sprawdzania poczty" in r.message for r in caplog.records)


def test_handle_new_mail_build_system_prompt_fails_aborts_batch(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="harness.watcher")
    monkeypatch.setattr(W.mailbox, "select_folder",
                         lambda client, folder: FolderInfo(uid_validity=7, uid_next=99))
    monkeypatch.setattr(W.mailbox, "fetch_new", lambda client, since_uid: [_msg(5, "<1@x>")])

    def boom(use_skill):
        raise FileNotFoundError("SKILL.md missing")

    monkeypatch.setattr(W.skill_prompt, "build_system_prompt", boom)
    monkeypatch.setattr(W, "run_agent", lambda *a, **kw: pytest.fail("nie powinno być wywołane"))

    state = _baseline_state()
    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=state)

    assert result == state
    assert len(caplog.records) >= 1


def test_handle_new_mail_get_provider_fails_aborts_batch(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="harness.watcher")
    monkeypatch.setattr(W.mailbox, "select_folder",
                         lambda client, folder: FolderInfo(uid_validity=7, uid_next=99))
    monkeypatch.setattr(W.mailbox, "fetch_new", lambda client, since_uid: [_msg(5, "<1@x>")])
    monkeypatch.setattr(W.skill_prompt, "build_system_prompt", lambda use_skill: "SYSTEM")

    def boom(*a, **kw):
        raise ValueError("Nieznany dostawca AI")

    monkeypatch.setattr(W.providers, "get_provider", boom)
    monkeypatch.setattr(W, "run_agent", lambda *a, **kw: pytest.fail("nie powinno być wywołane"))

    state = _baseline_state()
    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=state)

    assert result == state
    assert len(caplog.records) >= 1


# --------------------------------------------------------------------------- per-message failures
# Uwaga: znacznik UID nie może przeskoczyć nieudanej wiadomości (inaczej nigdy by nie
# wróciła do przetworzenia), więc porażka w środku partii ZATRZYMUJE cały cykl – kolejne
# wiadomości z tej partii czekają do następnego wywołania handle_new_mail, nie do tego samego.
def test_handle_new_mail_build_user_message_fails_stops_batch_before_it(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="harness.watcher")
    _wire_happy_defaults(monkeypatch, [_msg(5, "<boom@x>", plain_text="BOOM"), _msg(6, "<ok@x>", plain_text="ok")])

    def flaky(body):
        if body == "BOOM":
            raise RuntimeError("zła wiadomość")
        return f"wrapped:{body}"

    monkeypatch.setattr(W.skill_prompt, "build_user_message", flaky)
    monkeypatch.setattr(W.mailbox, "append_draft", lambda client, folder, raw: None)

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=_baseline_state())

    assert result.is_processed("<boom@x>") is False
    assert result.is_processed("<ok@x>") is False  # nie dotarliśmy do niej w tym cyklu
    assert result.last_uid == 0  # znacznik nie przesunął się za nieudaną wiadomość
    assert len(caplog.records) >= 1


def test_handle_new_mail_run_agent_fails_stops_batch_before_it(monkeypatch):
    _wire_happy_defaults(monkeypatch, [_msg(5, "<1@x>"), _msg(6, "<2@x>")])

    def flaky(provider, system, user_message, tools, stop_tool):
        raise AgentDidNotActError("model się nie odezwał")

    monkeypatch.setattr(W, "run_agent", flaky)
    monkeypatch.setattr(W.mailbox, "append_draft", lambda client, folder, raw: None)

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=_baseline_state())

    assert result.is_processed("<1@x>") is False
    assert result.is_processed("<2@x>") is False
    assert result.last_uid == 0


def test_handle_new_mail_malformed_tool_input_stops_batch_before_it(monkeypatch):
    _wire_happy_defaults(monkeypatch, [_msg(5, "<bad@x>"), _msg(6, "<good@x>")])

    monkeypatch.setattr(W, "run_agent", lambda *a, **kw: ToolCall(
        id="c", name="create_draft", raw_input={"subject": "x"}  # brak wymaganych pól
    ))
    monkeypatch.setattr(W.mailbox, "append_draft", lambda client, folder, raw: None)

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=_baseline_state())

    assert result.is_processed("<bad@x>") is False
    assert result.is_processed("<good@x>") is False
    assert result.last_uid == 0


def test_handle_new_mail_build_draft_mime_fails_stops_batch_before_it(monkeypatch):
    _wire_happy_defaults(monkeypatch, [_msg(5, "<1@x>"), _msg(6, "<2@x>")])

    def boom(original, from_addr, decision):
        raise RuntimeError("nie udało się zbudować MIME")

    monkeypatch.setattr(W.mailbox, "build_draft_mime", boom)
    monkeypatch.setattr(W.mailbox, "append_draft", lambda client, folder, raw: None)

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=_baseline_state())

    assert result.is_processed("<1@x>") is False
    assert result.is_processed("<2@x>") is False
    assert result.last_uid == 0


def test_handle_new_mail_append_draft_fails_message_not_marked(monkeypatch):
    _wire_happy_defaults(monkeypatch, [_msg(5, "<1@x>")])

    def boom(client, folder, raw):
        raise ConnectionError("APPEND nie powiodło się")

    monkeypatch.setattr(W.mailbox, "append_draft", boom)

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=_baseline_state())

    assert result.is_processed("<1@x>") is False
    assert result.last_uid == 0


def test_handle_new_mail_retries_failed_message_on_next_call(monkeypatch):
    # Symulacja dwóch kolejnych cykli: pierwszy ląduje na błędzie przy drugiej wiadomości,
    # drugi (po "naprawie") przetwarza ją normalnie i dociera też do trzeciej.
    fetched = [_msg(5, "<1@x>"), _msg(6, "<2@x>"), _msg(7, "<3@x>")]
    calls = {"n": 0}

    def flaky(provider, system, user_message, tools, stop_tool):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AgentDidNotActError("chwilowy błąd")
        return _good_tool_call()

    _wire_happy_defaults(monkeypatch, fetched)
    monkeypatch.setattr(W, "run_agent", flaky)
    monkeypatch.setattr(W.mailbox, "append_draft", lambda client, folder, raw: None)

    state = _baseline_state()
    state = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=state)
    assert state.last_uid == 0  # <1@x> padł jako pierwszy – nic się nie przesunęło

    # kolejny cykl – fetch_new (teraz since_uid=0) wraca do tej samej trójki, <1@x> się udaje
    state = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=state)
    assert state.is_processed("<1@x>") is True
    assert state.is_processed("<2@x>") is True
    assert state.is_processed("<3@x>") is True
    assert state.last_uid == 7


# --------------------------------------------------------------------------- state.save failure
def test_handle_new_mail_state_save_fails_still_marks_in_memory(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="harness.watcher")
    _wire_happy_defaults(monkeypatch, [_msg(5, "<1@x>")])
    monkeypatch.setattr(W.mailbox, "append_draft", lambda client, folder, raw: None)

    def boom(self, path):
        raise OSError("brak miejsca na dysku")

    monkeypatch.setattr(ProcessedState, "save", boom)

    result = W.handle_new_mail(_cfg(), client="FAKE_CLIENT", state=_baseline_state())

    assert result.is_processed("<1@x>") is True
    assert any("zapisać stanu" in r.message for r in caplog.records)


# --------------------------------------------------------------------------- run() routing
def test_run_routes_to_poll_loop(monkeypatch):
    calls = []
    monkeypatch.setattr(W, "poll_loop", lambda cfg: calls.append("poll"))
    monkeypatch.setattr(W, "idle_loop", lambda cfg: calls.append("idle"))
    W.run(_cfg(detection_mode="poll"))
    assert calls == ["poll"]


def test_run_routes_to_idle_loop(monkeypatch):
    calls = []
    monkeypatch.setattr(W, "poll_loop", lambda cfg: calls.append("poll"))
    monkeypatch.setattr(W, "idle_loop", lambda cfg: calls.append("idle"))
    W.run(_cfg(detection_mode="idle"))
    assert calls == ["idle"]
