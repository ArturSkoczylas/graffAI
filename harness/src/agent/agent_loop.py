from __future__ import annotations

from typing import Callable, Optional

from .providers.base import BaseProvider, ToolCall, ToolSpec

MAX_TURNS = 8


class AgentDidNotActError(RuntimeError):
    pass


def run_agent(
    provider: BaseProvider,
    system: str,
    user_message: str,
    tools: list[ToolSpec],
    stop_tool: str,
    executors: Optional[dict[str, Callable[[ToolCall], str]]] = None,
) -> ToolCall:
    """Prowadzi pętlę wywołań narzędzi, aż model wywoła `stop_tool`; zwraca to wywołanie."""
    executors = executors or {}
    messages = provider.start_conversation(system, user_message)

    for _ in range(MAX_TURNS):
        reply = provider.step(system, messages, tools)
        messages.append(reply.assistant_message)

        if not reply.tool_calls:
            raise AgentDidNotActError(
                f"Model zakończył bez wywołania narzędzia {stop_tool!r}: {reply.text!r}"
            )

        for call in reply.tool_calls:
            if call.name == stop_tool:
                return call

            executor = executors.get(call.name)
            if executor is None:
                result, is_error = f"Nieznane narzędzie: {call.name}", True
            else:
                try:
                    result, is_error = executor(call), False
                except Exception as exc:  # noqa: BLE001 - narzędzie może zawieść w dowolny sposób
                    result, is_error = f"Błąd narzędzia {call.name}: {exc}", True
            messages.extend(provider.tool_result_messages(call, result, is_error))

    raise AgentDidNotActError(f"Przekroczono limit {MAX_TURNS} tur bez wywołania {stop_tool!r}")
