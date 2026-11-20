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
        """Build the native message list that starts the conversation."""

    @abstractmethod
    def step(self, system: str, messages: list[Any], tools: list[ToolSpec]) -> ProviderReply:
        """Make a single call to the model. The caller appends reply.assistant_message to messages."""

    @abstractmethod
    def tool_result_messages(self, tool_call: ToolCall, result: str, is_error: bool = False) -> list[Any]:
        """Native message(s) representing the tool result, to append to the history."""
