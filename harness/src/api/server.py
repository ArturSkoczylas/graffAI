from __future__ import annotations

import email
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..agent import print_check, providers, run_script, skill_prompt, skills_registry
from ..agent.agent_loop import run_agent
from ..agent.skill_prompt import DraftDecision
from ..config import Config
from ..mail_listener import mailbox

log = logging.getLogger("harness.api")


def create_draft_from_raw_email(cfg: Config, raw: bytes) -> DraftDecision:
    """Buduje szkic odpowiedzi z surowej wiadomości (RFC822, np. z messenger.messages.getRaw()
    w rozszerzeniu Thunderbirda) i zapisuje go do Szkiców IMAP – ten sam mechanizm co watcher,
    tylko wywołany na żądanie dla jednej, już posiadanej wiadomości."""
    original = email.message_from_bytes(raw)
    plain_text = mailbox.extract_plain_text(original)
    attachments = mailbox.extract_attachments(original)

    tools = [
        skill_prompt.CREATE_DRAFT_TOOL,
        skills_registry.build_read_skill_tool(),
        run_script.build_run_skill_script_tool(),
    ]
    executors = {
        "read_skill": skills_registry.make_read_skill_executor(),
        "run_skill_script": run_script.make_run_skill_script_executor(),
    }
    if attachments:
        tools.append(print_check.build_check_print_file_tool())
        executors["check_print_file"] = print_check.make_check_print_file_executor(attachments)

    system_prompt = skill_prompt.build_system_prompt(has_attachments=bool(attachments))
    provider = providers.get_provider(
        cfg.ai_provider, model=cfg.ai_model, api_key=cfg.ai_api_key, max_tokens=cfg.ai_max_tokens,
    )
    user_message = skill_prompt.build_user_message(
        plain_text, attachment_filenames=[a.filename for a in attachments],
    )
    tool_call = run_agent(
        provider, system_prompt, user_message,
        tools=tools, stop_tool="create_draft", executors=executors,
    )
    decision = DraftDecision.model_validate(tool_call.raw_input)

    draft_bytes = mailbox.build_draft_mime(original, cfg.from_address, decision)
    client = mailbox.connect(cfg)
    try:
        mailbox.append_draft(client, cfg.drafts_folder, draft_bytes)
    finally:
        client.logout()
    return decision


def handle_draft_request(cfg: Config, raw: bytes) -> tuple[int, dict[str, Any]]:
    """Czysta funkcja: surowe bajty wiadomości -> (kod HTTP, treść JSON). Bez I/O sieciowego –
    to pozwala testować obsługę żądania bez stawiania prawdziwego serwera."""
    if not raw:
        return 400, {"status": "error", "message": "Puste żądanie – brak treści wiadomości"}
    try:
        decision = create_draft_from_raw_email(cfg, raw)
    except Exception as exc:
        log.exception("Nie udało się przygotować szkicu")
        return 500, {"status": "error", "message": str(exc)}
    return 200, {"status": "ok", "subject": decision.subject, "needs_human": decision.needs_human}


class _DraftHandler(BaseHTTPRequestHandler):
    cfg: Config

    def do_POST(self) -> None:
        if self.path != "/draft":
            self._respond(404, {"status": "error", "message": "Nieznana ścieżka"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        status, payload = handle_draft_request(self.cfg, raw)
        self._respond(status, payload)

    def _respond(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)


def make_server(cfg: Config) -> ThreadingHTTPServer:
    handler_cls = type("BoundDraftHandler", (_DraftHandler,), {"cfg": cfg})
    return ThreadingHTTPServer((cfg.api_host, cfg.api_port), handler_cls)


def run(cfg: Config) -> None:
    srv = make_server(cfg)
    log.info("Serwer HTTP nasłuchuje na %s:%s (POST /draft)", cfg.api_host, cfg.api_port)
    srv.serve_forever()
