from __future__ import annotations

import logging
import re
from email.message import EmailMessage, Message
from email.utils import make_msgid, parseaddr
from typing import Any, Callable, Optional

from ..agent.print_check import Attachment
from ..agent.skill_prompt import DraftDecision
from ..config import Config

log = logging.getLogger("harness.mailbox")

BANNER_TITLE = "[SZKIC WYGENEROWANY PRZEZ AI — SPRAWDŹ PRZED WYSŁANIEM]"
_RE_PREFIX = re.compile(r"^\s*(re|odp)\s*:\s*", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def connect(cfg: Config, client_factory: Optional[Callable[..., Any]] = None) -> Any:
    if client_factory is None:
        import imapclient
        client_factory = imapclient.IMAPClient
    client = client_factory(cfg.imap_host, port=cfg.imap_port, ssl=cfg.imap_use_ssl)
    client.login(cfg.imap_user, cfg.imap_password)
    return client


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return str(part.get_payload() or "")
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def extract_plain_text(msg: Message) -> str:
    if not msg.is_multipart():
        text = _decode_part(msg)
        return text if msg.get_content_type() == "text/plain" else _strip_html(text)

    plain = None
    html = None
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and plain is None:
            plain = _decode_part(part)
        elif ctype == "text/html" and html is None:
            html = _decode_part(part)
    if plain is not None:
        return plain
    if html is not None:
        return _strip_html(html)
    return ""


def extract_attachments(msg: Message) -> list[Attachment]:
    attachments = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = (part.get_content_disposition() or "").lower()
        if not filename and disposition != "attachment":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        attachments.append(Attachment(
            filename=filename or "załącznik",
            content_type=part.get_content_type(),
            data=payload,
        ))
    return attachments


def reply_subject(subject: Optional[str]) -> str:
    subject = (subject or "").strip()
    if not subject:
        return "Re: (bez tematu)"
    return subject if _RE_PREFIX.match(subject) else f"Re: {subject}"


def _banner(decision: DraftDecision) -> str:
    lines = [BANNER_TITLE]
    if decision.needs_human:
        lines.append("Wymaga człowieka: TAK")
    if decision.staff_notes:
        lines.append("Uwagi: " + decision.staff_notes)
    return "\n".join(lines)


def build_draft_mime(original: Message, from_addr: str, decision: DraftDecision) -> bytes:
    body = f"{_banner(decision)}\n\n{decision.body}".strip() + "\n"

    reply = EmailMessage()
    reply["From"] = from_addr
    _, to_addr = parseaddr(original.get("Reply-To") or original.get("From") or "")
    reply["To"] = to_addr
    reply["Subject"] = reply_subject(decision.subject)

    original_id = original.get("Message-ID")
    if original_id:
        reply["In-Reply-To"] = original_id
        references = original.get("References", "")
        reply["References"] = f"{references} {original_id}".strip()

    reply["Message-ID"] = make_msgid()
    reply.set_content(body)
    return reply.as_bytes()


def append_draft(client: Any, folder: str, mime_bytes: bytes) -> None:
    client.append(folder, mime_bytes, flags=[b"\\Draft"])
