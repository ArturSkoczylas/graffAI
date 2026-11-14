from __future__ import annotations

import email
import logging
import re
from dataclasses import dataclass
from email.message import EmailMessage, Message
from email.utils import make_msgid, parseaddr
from typing import Any, Callable, Optional

from ..agent.skill_prompt import DraftDecision
from ..config import Config

log = logging.getLogger("harness.mailbox")

BANNER_TITLE = "[SZKIC WYGENEROWANY PRZEZ AI — SPRAWDŹ PRZED WYSŁANIEM]"
_RE_PREFIX = re.compile(r"^\s*(re|odp)\s*:\s*", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class FetchedMessage:
    uid: int
    message_id: str
    plain_text: str
    original: Message


@dataclass(frozen=True)
class FolderInfo:
    uid_validity: int
    uid_next: int


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


def reply_subject(subject: Optional[str]) -> str:
    subject = (subject or "").strip()
    if not subject:
        return "Re: (bez tematu)"
    return subject if _RE_PREFIX.match(subject) else f"Re: {subject}"


def select_folder(client: Any, folder: str) -> FolderInfo:
    info = client.select_folder(folder)
    return FolderInfo(uid_validity=info[b"UIDVALIDITY"], uid_next=info[b"UIDNEXT"])


def fetch_new(client: Any, since_uid: int) -> list[FetchedMessage]:
    """Zwraca wiadomości z UID > since_uid. Zakłada, że folder jest już wybrany
    (select_folder) – nie opiera się na fladze \\Seen, tylko na pozycji w skrzynce."""
    uids = client.search(["UID", f"{since_uid + 1}:*"])
    if not uids:
        return []

    response = client.fetch(uids, ["RFC822"])
    results = []
    for uid, data in response.items():
        if uid <= since_uid:
            # niektóre serwery mogą dociągnąć też starszy UID na granicy zakresu
            continue
        raw = data[b"RFC822"]
        original = email.message_from_bytes(raw)
        message_id = original.get("Message-ID") or f"<no-id-{uid}@mail-harness>"
        try:
            plain_text = extract_plain_text(original)
        except Exception:
            log.exception("Nie udało się odczytać treści wiadomości uid=%s", uid)
            plain_text = ""
        results.append(FetchedMessage(uid=uid, message_id=message_id, plain_text=plain_text, original=original))
    results.sort(key=lambda m: m.uid)
    return results


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
