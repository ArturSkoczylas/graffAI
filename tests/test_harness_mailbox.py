"""Testy harness/mailbox.py – parsowanie e-maili, budowa szkicu, IMAP (na fałszywym kliencie)."""
import email as email_module
import sys
from email import policy
from email.message import EmailMessage, Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.mail_listener import mailbox as M  # noqa: E402
from harness.src.config import Config  # noqa: E402
from harness.src.agent.skill_prompt import DraftDecision  # noqa: E402


def _multipart(plain=None, html=None, attachment=False):
    msg = EmailMessage()
    msg["From"] = "klient@example.com"
    msg["Subject"] = "Pytanie"
    if plain is not None and html is not None:
        msg.set_content(plain)
        msg.add_alternative(html, subtype="html")
    elif plain is not None:
        msg.set_content(plain)
    elif html is not None:
        msg.set_content("placeholder")
        msg.replace_header("Content-Type", "text/html; charset=\"utf-8\"")
        msg.set_payload(html)
    if attachment:
        msg.add_attachment(b"%PDF-1.7 fake", maintype="application", subtype="pdf", filename="projekt.pdf")
    return msg


# --------------------------------------------------------------------------- extract_plain_text
def test_extract_plain_text_simple():
    msg = EmailMessage()
    msg.set_content("Dzień dobry,\ntreść.")
    assert M.extract_plain_text(msg).strip() == "Dzień dobry,\ntreść."


def test_extract_plain_text_prefers_plain_over_html():
    msg = _multipart(plain="wersja tekstowa", html="<p>wersja html</p>")
    assert M.extract_plain_text(msg).strip() == "wersja tekstowa"


def test_extract_plain_text_html_only_strips_tags():
    raw = (
        b"From: a@b.com\r\n"
        b"Subject: x\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><script>evil()</script><p>Tre\xc5\x9b\xc4\x87 "
        b"<b>pogrubiona</b></p></body></html>"
    )
    msg = email_module.message_from_bytes(raw)
    text = M.extract_plain_text(msg)
    assert "evil" not in text
    assert "Treść" in text
    assert "<" not in text


def test_extract_plain_text_attachment_only_returns_empty():
    msg = EmailMessage()
    msg["From"] = "a@b.com"
    msg.set_content("")
    msg.add_attachment(b"%PDF-1.7 fake", maintype="application", subtype="pdf", filename="projekt.pdf")
    # usuwamy pustą część tekstową żeby zasymulować maila bez treści, tylko z załącznikiem
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            part.set_payload(None)
    text = M.extract_plain_text(msg)
    assert text == ""


def test_extract_plain_text_bogus_charset_falls_back_to_utf8():
    msg = EmailMessage()
    msg["From"] = "a@b.com"
    msg.add_header("Content-Type", "text/plain", charset="made-up-9000")
    msg.set_payload("Zażółć gęślą jaźń".encode("utf-8"))
    text = M.extract_plain_text(msg)
    assert "Zażółć" in text


def test_extract_plain_text_polish_diacritics_round_trip():
    msg = EmailMessage()
    msg.set_content("Zażółć gęślą jaźń – dziękuję i pozdrawiam.")
    assert "Zażółć gęślą jaźń" in M.extract_plain_text(msg)


def test_extract_plain_text_nested_multipart_finds_plain():
    inner = EmailMessage()
    inner.set_content("tekst wewnątrz")
    inner.add_alternative("<p>html wewnątrz</p>", subtype="html")

    outer = EmailMessage()
    outer["From"] = "a@b.com"
    outer.make_mixed()
    outer.attach(inner)
    assert "tekst wewnątrz" in M.extract_plain_text(outer)


# --------------------------------------------------------------------------- reply_subject
def test_reply_subject_happy_path():
    assert M.reply_subject("Zapytanie o ofertę") == "Re: Zapytanie o ofertę"


@pytest.mark.parametrize("subject", [None, "", "   "])
def test_reply_subject_blank_input(subject):
    assert M.reply_subject(subject) == "Re: (bez tematu)"


@pytest.mark.parametrize("subject", ["Re: coś", "RE: coś", "re: coś", "Odp: coś"])
def test_reply_subject_already_prefixed_unchanged(subject):
    assert M.reply_subject(subject) == subject


def test_reply_subject_fwd_gets_re_prepended():
    assert M.reply_subject("Fwd: coś") == "Re: Fwd: coś"


def test_reply_subject_long_subject_untouched_aside_from_prefix():
    long_subject = "x" * 500
    assert M.reply_subject(long_subject) == f"Re: {long_subject}"


# --------------------------------------------------------------------------- select_folder / fetch_new (fake client)
class FakeImapClient:
    def __init__(self, raw_by_uid, uid_validity=7, uid_next=None):
        self._raw_by_uid = raw_by_uid
        self._uid_validity = uid_validity
        self._uid_next = uid_next if uid_next is not None else (max(raw_by_uid, default=0) + 1)
        self.selected_folder = None
        self.fetch_called = False
        self.search_criteria = None

    def select_folder(self, folder):
        self.selected_folder = folder
        return {b"UIDVALIDITY": self._uid_validity, b"UIDNEXT": self._uid_next}

    def search(self, criteria):
        self.search_criteria = criteria
        _, rng = criteria
        lo = int(rng.split(":")[0])
        return [uid for uid in self._raw_by_uid if uid >= lo]

    def fetch(self, uids, parts):
        self.fetch_called = True
        return {uid: {b"RFC822": self._raw_by_uid[uid]} for uid in uids}


def _raw(subject="Pytanie", message_id="<a@x>", body="treść"):
    msg = EmailMessage()
    msg["From"] = "klient@example.com"
    msg["Subject"] = subject
    if message_id is not None:
        msg["Message-ID"] = message_id
    msg.set_content(body)
    return msg.as_bytes()


def test_select_folder_returns_folder_info():
    client = FakeImapClient({}, uid_validity=42, uid_next=7)
    info = M.select_folder(client, "INBOX")
    assert client.selected_folder == "INBOX"
    assert info.uid_validity == 42
    assert info.uid_next == 7


def test_fetch_new_happy_two_messages():
    client = FakeImapClient({1: _raw(message_id="<1@x>", body="pierwsza"),
                              2: _raw(message_id="<2@x>", body="druga")})
    result = M.fetch_new(client, since_uid=0)
    assert [m.uid for m in result] == [1, 2]
    assert [m.message_id for m in result] == ["<1@x>", "<2@x>"]
    assert result[0].plain_text.strip() == "pierwsza"


def test_fetch_new_only_returns_uids_above_since():
    client = FakeImapClient({1: _raw(message_id="<1@x>"), 2: _raw(message_id="<2@x>"),
                              3: _raw(message_id="<3@x>")})
    result = M.fetch_new(client, since_uid=1)
    assert [m.uid for m in result] == [2, 3]


def test_fetch_new_empty_search_skips_fetch():
    client = FakeImapClient({})
    result = M.fetch_new(client, since_uid=0)
    assert result == []
    assert client.fetch_called is False


def test_fetch_new_boundary_uid_equal_to_since_is_excluded():
    # serwer może na granicy zakresu "n:*" dociągnąć też UID == since_uid; filtrujemy to.
    client = FakeImapClient({5: _raw(message_id="<5@x>"), 6: _raw(message_id="<6@x>")})
    client.search = lambda criteria: [5, 6]  # symulacja serwera zwracającego też granicę
    result = M.fetch_new(client, since_uid=5)
    assert [m.uid for m in result] == [6]


def test_fetch_new_results_sorted_by_uid():
    client = FakeImapClient({3: _raw(message_id="<3@x>"), 1: _raw(message_id="<1@x>"),
                              2: _raw(message_id="<2@x>")})
    result = M.fetch_new(client, since_uid=0)
    assert [m.uid for m in result] == [1, 2, 3]


def test_fetch_new_missing_message_id_gets_placeholder():
    client = FakeImapClient({1: _raw(message_id=None)})
    result = M.fetch_new(client, since_uid=0)
    assert result[0].message_id.startswith("<no-id-")


def test_fetch_new_truncated_bytes_does_not_crash():
    full = _raw(body="treść" * 50)
    truncated = full[: len(full) // 2]
    client = FakeImapClient({1: truncated})
    result = M.fetch_new(client, since_uid=0)
    assert len(result) == 1


def test_fetch_new_extract_plain_text_returns_empty(monkeypatch):
    monkeypatch.setattr(M, "extract_plain_text", lambda msg: "")
    client = FakeImapClient({1: _raw()})
    result = M.fetch_new(client, since_uid=0)
    assert result[0].plain_text == ""


def test_fetch_new_extract_plain_text_raises_for_one_message_continues(monkeypatch):
    calls = {"n": 0}

    def flaky(msg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("uszkodzony mail")
        return "ok"

    monkeypatch.setattr(M, "extract_plain_text", flaky)
    client = FakeImapClient({1: _raw(message_id="<1@x>"), 2: _raw(message_id="<2@x>")})
    result = M.fetch_new(client, since_uid=0)
    assert len(result) == 2
    assert result[0].plain_text == ""
    assert result[1].plain_text == "ok"


# --------------------------------------------------------------------------- build_draft_mime
def _original(subject="Pytanie o ofertę", message_id="<abc@klient>", from_addr="Jan Klient <jan@klient.com>",
              reply_to=None) -> Message:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    if message_id is not None:
        msg["Message-ID"] = message_id
    if reply_to is not None:
        msg["Reply-To"] = reply_to
    msg.set_content("treść pytania")
    return msg


def _decision(subject="Pytanie o ofertę", body="Dzień dobry,\n\ntreść.", needs_human=False, staff_notes=""):
    return DraftDecision(subject=subject, body=body, needs_human=needs_human, staff_notes=staff_notes)


def test_build_draft_mime_happy_path():
    raw = M.build_draft_mime(_original(), "biuro@drukarnia.pl", _decision())
    reply = email_module.message_from_bytes(raw, policy=policy.default)
    assert reply["To"] == "jan@klient.com"
    assert reply["Subject"] == "Re: Pytanie o ofertę"
    assert reply["In-Reply-To"] == "<abc@klient>"
    assert "<abc@klient>" in reply["References"]
    assert "treść." in reply.get_content()


def test_build_draft_mime_uses_reply_to_over_from():
    raw = M.build_draft_mime(_original(reply_to="inny@klient.com"), "biuro@drukarnia.pl", _decision())
    reply = email_module.message_from_bytes(raw, policy=policy.default)
    assert reply["To"] == "inny@klient.com"


def test_build_draft_mime_missing_message_id_no_crash():
    raw = M.build_draft_mime(_original(message_id=None), "biuro@drukarnia.pl", _decision())
    reply = email_module.message_from_bytes(raw, policy=policy.default)
    assert reply["In-Reply-To"] is None
    assert reply["References"] is None


def test_build_draft_mime_minimal_banner_when_no_flags():
    raw = M.build_draft_mime(_original(), "biuro@drukarnia.pl", _decision(needs_human=False, staff_notes=""))
    reply = email_module.message_from_bytes(raw, policy=policy.default)
    content = reply.get_content()
    assert "Wymaga człowieka" not in content
    assert "Uwagi:" not in content


def test_build_draft_mime_banner_with_flags():
    raw = M.build_draft_mime(
        _original(), "biuro@drukarnia.pl",
        _decision(needs_human=True, staff_notes="sprawdzić cenę"),
    )
    reply = email_module.message_from_bytes(raw, policy=policy.default)
    content = reply.get_content()
    assert "Wymaga człowieka: TAK" in content
    assert "sprawdzić cenę" in content


def test_build_draft_mime_polish_diacritics_round_trip():
    raw = M.build_draft_mime(_original(), "biuro@drukarnia.pl", _decision(body="Zażółć gęślą jaźń"))
    reply = email_module.message_from_bytes(raw, policy=policy.default)
    assert "Zażółć gęślą jaźń" in reply.get_content()


def test_build_draft_mime_malformed_from_header_no_crash():
    raw = M.build_draft_mime(_original(from_addr=""), "biuro@drukarnia.pl", _decision())
    reply = email_module.message_from_bytes(raw, policy=policy.default)
    assert reply["To"] == ""


def test_build_draft_mime_propagates_reply_subject_failure(monkeypatch):
    monkeypatch.setattr(M, "reply_subject", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        M.build_draft_mime(_original(), "biuro@drukarnia.pl", _decision())


# --------------------------------------------------------------------------- connect
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


class SuccessConnection:
    def __init__(self, host, port, ssl):
        self.host, self.port, self.ssl = host, port, ssl
        self.login_args = None
        self.is_connected = False

    def login(self, user, password):
        self.login_args = (user, password)
        self.is_connected = True


class FailedConnection:
    def __init__(self, host, port, ssl):
        pass

    def login(self, user, password):
        raise ConnectionError("złe dane logowania")


def test_connect_success():
    created = {}

    def factory(host, port, ssl):
        created["client"] = SuccessConnection(host, port, ssl)
        return created["client"]

    client = M.connect(_cfg(), client_factory=factory)
    assert client.is_connected is True
    assert client.login_args == ("biuro@example.com", "tajne")
    assert client.host == "imap.example.com"
    assert client.port == 993
    assert client.ssl is True


def test_connect_login_failure_propagates():
    def factory(host, port, ssl):
        return FailedConnection(host, port, ssl)

    with pytest.raises(ConnectionError):
        M.connect(_cfg(), client_factory=factory)


def test_connect_factory_failure_propagates():
    def factory(host, port, ssl):
        raise OSError("połączenie odrzucone")

    with pytest.raises(OSError):
        M.connect(_cfg(), client_factory=factory)


# --------------------------------------------------------------------------- append_draft
def test_append_draft_calls_client_with_correct_args():
    calls = []

    class FakeClient:
        def append(self, folder, mime_bytes, flags):
            calls.append((folder, mime_bytes, flags))

    M.append_draft(FakeClient(), "Drafts", b"raw-mime")
    assert calls == [("Drafts", b"raw-mime", [b"\\Draft"])]
