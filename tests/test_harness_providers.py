"""Tests for harness/providers/ - base.py, anthropic_provider.py, __init__.py (get_provider)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.agent.providers.base import BaseProvider, ProviderReply, ToolCall, ToolSpec  # noqa: E402
from harness.src.agent.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from harness.src.agent.providers import get_provider  # noqa: E402


# --------------------------------------------------------------------------- BaseProvider (ABC)
def test_base_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        BaseProvider(model="x", api_key="y")


class _DummyProvider(BaseProvider):
    def start_conversation(self, system, user_message):
        return [{"role": "user", "content": user_message}]

    def step(self, system, messages, tools):
        return ProviderReply(assistant_message={}, text="ok", tool_calls=[], stop_reason="end_turn")

    def tool_result_messages(self, tool_call, result, is_error=False):
        return [{"tool_use_id": tool_call.id, "content": result, "is_error": is_error}]


def test_minimal_concrete_subclass_instantiates_and_works():
    provider = _DummyProvider(model="dummy-model", api_key="k")
    messages = provider.start_conversation("sys", "hello")
    reply = provider.step("sys", messages, tools=[])
    assert reply.text == "ok"


# --------------------------------------------------------------------------- AnthropicProvider.__init__
def test_anthropic_provider_init_defaults():
    p = AnthropicProvider(model="claude-sonnet-5-5", api_key="sk-test")
    assert p.model == "claude-sonnet-5-5"
    assert p.api_key == "sk-test"
    assert p.options["max_tokens"] == 3000


def test_anthropic_provider_init_custom_max_tokens():
    p = AnthropicProvider(model="claude-sonnet-5-5", api_key="sk-test", max_tokens=500)
    assert p.options["max_tokens"] == 500


# --------------------------------------------------------------------------- start_conversation
def test_start_conversation_happy_path():
    p = AnthropicProvider(model="m", api_key="k")
    messages = p.start_conversation("system prompt", "Dzień dobry")
    assert messages == [{"role": "user", "content": "Dzień dobry"}]


def test_start_conversation_empty_user_message():
    p = AnthropicProvider(model="m", api_key="k")
    messages = p.start_conversation("system prompt", "")
    assert messages == [{"role": "user", "content": ""}]


# --------------------------------------------------------------------------- step
def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def _fake_response(content, stop_reason="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


def test_step_text_and_tool_use(monkeypatch):
    p = AnthropicProvider(model="m", api_key="k")
    response = _fake_response(
        [_text_block("oto szkic"), _tool_use_block("call_1", "create_draft", {"subject": "Re: x"})]
    )
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(p._client.messages, "create", fake_create)
    reply = p.step("system", [{"role": "user", "content": "hi"}], tools=[
        ToolSpec(name="create_draft", description="d", input_schema={"type": "object"})
    ])
    assert reply.text == "oto szkic"
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0] == ToolCall(id="call_1", name="create_draft", raw_input={"subject": "Re: x"})
    assert reply.stop_reason == "end_turn"
    assert captured["tools"] == [{"name": "create_draft", "description": "d", "input_schema": {"type": "object"}}]


def test_step_text_only_no_tool_calls(monkeypatch):
    p = AnthropicProvider(model="m", api_key="k")
    response = _fake_response([_text_block("tylko tekst")])
    monkeypatch.setattr(p._client.messages, "create", lambda **kw: response)
    reply = p.step("system", [], tools=[])
    assert reply.tool_calls == []


def test_step_multiple_tool_use_blocks_in_order(monkeypatch):
    p = AnthropicProvider(model="m", api_key="k")
    response = _fake_response([
        _tool_use_block("c1", "tool_a", {"x": 1}),
        _tool_use_block("c2", "tool_b", {"y": 2}),
    ])
    monkeypatch.setattr(p._client.messages, "create", lambda **kw: response)
    reply = p.step("system", [], tools=[])
    assert [c.name for c in reply.tool_calls] == ["tool_a", "tool_b"]


def test_step_multiple_text_blocks_concatenated(monkeypatch):
    p = AnthropicProvider(model="m", api_key="k")
    response = _fake_response([_text_block("część 1 "), _text_block("część 2")])
    monkeypatch.setattr(p._client.messages, "create", lambda **kw: response)
    reply = p.step("system", [], tools=[])
    assert reply.text == "część 1 część 2"


# --------------------------------------------------------------------------- tool_result_messages
def test_tool_result_messages_happy_path():
    p = AnthropicProvider(model="m", api_key="k")
    msgs = p.tool_result_messages(ToolCall(id="c1", name="create_draft", raw_input={}), "wynik")
    assert msgs == [{
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "wynik", "is_error": False}],
    }]


def test_tool_result_messages_is_error_true():
    p = AnthropicProvider(model="m", api_key="k")
    msgs = p.tool_result_messages(ToolCall(id="c1", name="x", raw_input={}), "błąd", is_error=True)
    assert msgs[0]["content"][0]["is_error"] is True


def test_tool_result_messages_empty_result():
    p = AnthropicProvider(model="m", api_key="k")
    msgs = p.tool_result_messages(ToolCall(id="c1", name="x", raw_input={}), "")
    assert msgs[0]["content"][0]["content"] == ""


# --------------------------------------------------------------------------- _to_native_tool
def test_to_native_tool_exact_shape():
    tool = ToolSpec(name="create_draft", description="desc", input_schema={"type": "object"})
    native = AnthropicProvider._to_native_tool(tool)
    assert native == {"name": "create_draft", "description": "desc", "input_schema": {"type": "object"}}


# --------------------------------------------------------------------------- get_provider
@pytest.mark.parametrize("name", ["claude", "anthropic", "CLAUDE", "Anthropic"])
def test_get_provider_resolves_to_anthropic(name):
    provider = get_provider(name, model="claude-sonnet-5-5", api_key="sk-test")
    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "claude-sonnet-5-5"
    assert provider.api_key == "sk-test"


@pytest.mark.parametrize("name", ["openai", "gpt"])
def test_get_provider_known_not_implemented(name):
    with pytest.raises(NotImplementedError):
        get_provider(name, model="x", api_key="k")


@pytest.mark.parametrize("name", ["", "   ", "mistral"])
def test_get_provider_unknown_raises_value_error(name):
    with pytest.raises(ValueError):
        get_provider(name, model="x", api_key="k")


def test_get_provider_forwards_extra_options():
    provider = get_provider("claude", model="m", api_key="k", max_tokens=500)
    assert provider.options["max_tokens"] == 500
