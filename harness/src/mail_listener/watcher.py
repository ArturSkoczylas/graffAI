from __future__ import annotations

import logging
import time
from typing import Any

from ..agent import providers, skill_prompt
from ..agent.agent_loop import run_agent
from ..agent.skill_prompt import DraftDecision
from ..config import Config
from . import mailbox
from .state import ProcessedState

log = logging.getLogger("harness.watcher")


def _save_state(cfg: Config, state: ProcessedState, context: str) -> None:
    try:
        state.save(cfg.state_file)
    except Exception:
        log.exception("Nie udało się zapisać stanu na dysku (%s)", context)


def handle_new_mail(cfg: Config, client: Any, state: ProcessedState) -> ProcessedState:
    try:
        info = mailbox.select_folder(client, cfg.inbox_folder)
    except Exception:
        log.exception("Nie udało się wybrać folderu %s", cfg.inbox_folder)
        return state

    if not state.has_baseline() or state.uid_validity != info.uid_validity:
        state = state.with_baseline(last_uid=info.uid_next - 1, uid_validity=info.uid_validity)
        log.info(
            "Punkt startowy ustawiony na UID=%s (uid_validity=%s) – pomijam istniejącą zawartość skrzynki",
            state.last_uid, info.uid_validity,
        )
        _save_state(cfg, state, "ustawienie punktu startowego")
        return state

    try:
        fetched = mailbox.fetch_new(client, since_uid=state.last_uid)
        system_prompt = skill_prompt.build_system_prompt(cfg.use_skill)
        provider = providers.get_provider(
            cfg.ai_provider, model=cfg.ai_model, api_key=cfg.ai_api_key, max_tokens=cfg.ai_max_tokens
        )
    except Exception:
        log.exception("Nie udało się przygotować cyklu sprawdzania poczty")
        return state

    for msg in fetched:
        if state.is_processed(msg.message_id):
            state = state.advance_uid(msg.uid)
            continue

        try:
            user_message = skill_prompt.build_user_message(msg.plain_text)
            tool_call = run_agent(
                provider, system_prompt, user_message,
                tools=[skill_prompt.CREATE_DRAFT_TOOL], stop_tool="create_draft",
            )
            decision = DraftDecision.model_validate(tool_call.raw_input)
            draft_bytes = mailbox.build_draft_mime(msg.original, cfg.from_address, decision)
            mailbox.append_draft(client, cfg.drafts_folder, draft_bytes)
        except Exception:
            log.exception(
                "Nie udało się przygotować szkicu dla uid=%s message-id=%s – zatrzymuję ten cykl, "
                "spróbuję ponownie od tej wiadomości w następnym", msg.uid, msg.message_id
            )
            break

        state = state.mark_processed(msg.message_id).advance_uid(msg.uid)
        _save_state(cfg, state, f"uid={msg.uid}")

    return state


def poll_loop(cfg: Config) -> None:
    state = ProcessedState.load(cfg.state_file)
    while True:
        try:
            client = mailbox.connect(cfg)
        except Exception:
            log.exception("Nie udało się połączyć z IMAP, ponawiam za %s s", cfg.poll_interval_seconds)
            time.sleep(cfg.poll_interval_seconds)
            continue
        try:
            state = handle_new_mail(cfg, client, state)
        finally:
            client.logout()
        time.sleep(cfg.poll_interval_seconds)


def idle_loop(cfg: Config) -> None:
    state = ProcessedState.load(cfg.state_file)
    while True:
        try:
            client = mailbox.connect(cfg)
        except Exception:
            log.exception("Nie udało się połączyć z IMAP, ponawiam za 10 s")
            time.sleep(10)
            continue

        try:
            state = handle_new_mail(cfg, client, state)
            while True:
                client.idle()
                responses = client.idle_check(timeout=300)
                client.idle_done()
                if responses:
                    state = handle_new_mail(cfg, client, state)
        except Exception:
            log.exception("Połączenie IMAP przerwane, ponawiam za 10 s")
            time.sleep(10)
        finally:
            try:
                client.logout()
            except Exception:
                pass


def run(cfg: Config) -> None:
    if cfg.detection_mode == "poll":
        poll_loop(cfg)
    else:
        idle_loop(cfg)
