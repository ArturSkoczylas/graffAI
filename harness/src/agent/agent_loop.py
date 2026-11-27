from __future__ import annotations

import logging
from typing import Callable, Optional

from .providers.base import BaseProvider, ToolCall, ToolSpec

MAX_TURNS = 8
_PREVIEW_CHARS = 300

log = logging.getLogger("harness.agent_loop")


class AgentDidNotActError(RuntimeError):
    pass


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _PREVIEW_CHARS else flat[:_PREVIEW_CHARS] + "…"


def run_agent(
    provider: BaseProvider,
    system: str,
    user_message: str,
    tools: list[ToolSpec],
    stop_tool: str,
    executors: Optional[dict[str, Callable[[ToolCall], str]]] = None,
) -> ToolCall:
    """Drives the tool-call loop until the model calls `stop_tool`; returns that call."""
    executors = executors or {}
    messages = provider.start_conversation(system, user_message)

    for turn in range(1, MAX_TURNS + 1):
        reply = provider.step(system, messages, tools)
        messages.append(reply.assistant_message)
        log.info(
            "turn %d/%d: stop_reason=%s tools=%s text=%r",
            turn, MAX_TURNS, reply.stop_reason,
            [c.name for c in reply.tool_calls] or "(none)", _preview(reply.text),
        )

        if not reply.tool_calls:
            raise AgentDidNotActError(
                f"Model zakończył bez wywołania narzędzia {stop_tool!r}: {reply.text!r}"
            )

        for call in reply.tool_calls:
            if call.name == stop_tool:
                log.info("turn %d: %s(id=%s) - stop_tool, loop finished", turn, call.name, call.id)
                return call

            executor = executors.get(call.name)
            if executor is None:
                result, is_error = f"Nieznane narzędzie: {call.name}", True
            else:
                try:
                    result, is_error = executor(call), False
                except Exception as exc:  # noqa: BLE001 - a tool can fail in any way
                    result, is_error = f"Błąd narzędzia {call.name}: {exc}", True
            log.info(
                "turn %d: %s(id=%s) -> %s: %r",
                turn, call.name, call.id, "ERROR" if is_error else "OK", _preview(result),
            )
            messages.extend(provider.tool_result_messages(call, result, is_error))

    raise AgentDidNotActError(f"Przekroczono limit {MAX_TURNS} tur bez wywołania {stop_tool!r}")
