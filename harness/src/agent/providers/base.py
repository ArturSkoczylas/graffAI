from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    raw_input: dict


@dataclass
class ProviderReply:
    assistant_message: Any
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str


class BaseProvider(ABC):
    def __init__(self, model: str, api_key: str, **options: Any) -> None:
        self.model = model
        self.api_key = api_key
        self.options = options

    @abstractmethod
    def start_conversation(self, system: str, user_message: str) -> list[Any]:
        """Zbuduj natywną listę wiadomości, od której zaczyna się rozmowa."""

    @abstractmethod
    def step(self, system: str, messages: list[Any], tools: list[ToolSpec]) -> ProviderReply:
        """Wykonaj jedno wywołanie modelu. Wywołujący dołącza reply.assistant_message do messages."""

    @abstractmethod
    def tool_result_messages(self, tool_call: ToolCall, result: str, is_error: bool = False) -> list[Any]:
        """Natywna wiadomość/wiadomości reprezentujące wynik narzędzia, do dołączenia do historii."""
