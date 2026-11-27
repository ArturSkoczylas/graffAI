from __future__ import annotations

from typing import Any

import anthropic

from .base import BaseProvider, ProviderReply, ToolCall, ToolSpec


class AnthropicProvider(BaseProvider):
    def __init__(self, model: str, api_key: str, max_tokens: int = 3000, **options: Any) -> None:
        super().__init__(model, api_key, max_tokens=max_tokens, **options)
        self._client = anthropic.Anthropic(api_key=api_key)

    def start_conversation(self, system: str, user_message: str) -> list[Any]:
        return [{"role": "user", "content": user_message}]

    def step(self, system: str, messages: list[Any], tools: list[ToolSpec]) -> ProviderReply:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.options["max_tokens"],
            system=system,
            messages=messages,
            tools=[self._to_native_tool(t) for t in tools],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, raw_input=b.input)
            for b in response.content if getattr(b, "type", "") == "tool_use"
        ]
        assistant_message = {"role": "assistant", "content": response.content}
        return ProviderReply(
            assistant_message=assistant_message,
            text=text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
        )

    def tool_result_messages(self, tool_call: ToolCall, result: str, is_error: bool = False) -> list[Any]:
        return [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result,
                "is_error": is_error,
            }],
        }]

    @staticmethod
    def _to_native_tool(tool: ToolSpec) -> dict:
        return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
