"""Tests for harness/mailbox.py - email parsing, draft building, IMAP (against a fake client)."""
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
    # remove the empty text part to simulate an email with no body, only an attachment
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


# --------------------------------------------------------------------------- extract_attachments
def test_extract_attachments_happy_path():
    attachments = M.extract_attachments(_multipart(plain="treść", attachment=True))
    assert [a.filename for a in attachments] == ["projekt.pdf"]
    assert attachments[0].content_type == "application/pdf"
    assert attachments[0].data == b"%PDF-1.7 fake"


def test_extract_attachments_no_attachment_returns_empty():
    assert M.extract_attachments(_multipart(plain="treść")) == []


def test_extract_attachments_plain_text_only_message_returns_empty():
    msg = EmailMessage()
    msg.set_content("bez multiparta")
    assert M.extract_attachments(msg) == []


def test_extract_attachments_multiple_attachments():
    msg = _multipart(plain="treść", attachment=True)
    msg.add_attachment(b"fake-jpeg", maintype="image", subtype="jpeg", filename="logo.jpg")
    attachments = M.extract_attachments(msg)
    assert sorted(a.filename for a in attachments) == ["logo.jpg", "projekt.pdf"]


def test_extract_attachments_ignores_inline_html_part():
    msg = _multipart(plain="treść", html="<p>html</p>", attachment=True)
    attachments = M.extract_attachments(msg)
    assert [a.filename for a in attachments] == ["projekt.pdf"]


def test_extract_attachments_empty_payload_skipped():
    msg = EmailMessage()
    msg.set_content("treść")
    msg.add_attachment(b"real", maintype="application", subtype="pdf", filename="a.pdf")
    for part in msg.walk():
        if part.get_filename() == "a.pdf":
            part.set_payload(b"")
    assert M.extract_attachments(msg) == []


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
        imap_password="tajne", imap_use_ssl=True, drafts_folder="Drafts",
        ai_provider="claude", ai_model="claude-sonnet-5-5", ai_api_key="sk-test",
        ai_max_tokens=3000, from_address="biuro@example.com",
        api_host="127.0.0.1", api_port=8765,
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
        raise ConnectionError("invalid login credentials")


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
        raise OSError("connection refused")

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
