"""Testy harness/agent_loop.py – generyczna pętla wywołań narzędzi, niezależna od dostawcy."""
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.agent.agent_loop import AgentDidNotActError, MAX_TURNS, run_agent  # noqa: E402
from harness.src.agent.providers.base import BaseProvider, ProviderReply, ToolCall  # noqa: E402


class FakeProvider(BaseProvider):
    """Dostawca-testowy: skryptowane odpowiedzi step(), opcjonalne usterki w innych metodach."""

    def __init__(self, step_results, start_conversation_error=None, tool_result_error=None):
        super().__init__(model="fake", api_key="fake")
        self._step_results = list(step_results)
        self._start_conversation_error = start_conversation_error
        self._tool_result_error = tool_result_error
        self.step_tools_seen = []
        self.tool_result_calls = []

    def start_conversation(self, system, user_message):
        if self._start_conversation_error:
            raise self._start_conversation_error
        return []

    def step(self, system, messages, tools):
        self.step_tools_seen.append(tools)
        result = self._step_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def tool_result_messages(self, tool_call, result, is_error=False):
        self.tool_result_calls.append((tool_call, result, is_error))
        if self._tool_result_error:
            raise self._tool_result_error
        return [{"tool_use_id": tool_call.id, "content": result, "is_error": is_error}]


def _reply(tool_calls=(), text="", stop_reason="tool_use"):
    return ProviderReply(assistant_message={}, text=text, tool_calls=list(tool_calls), stop_reason=stop_reason)


def _call(name, raw_input=None, id_="call_1"):
    return ToolCall(id=id_, name=name, raw_input=raw_input or {})


# --------------------------------------------------------------------------- happy path
def test_run_agent_returns_immediately_on_stop_tool():
    provider = FakeProvider([_reply([_call("create_draft", {"subject": "x"})])])
    result = run_agent(provider, "sys", "user", tools=[], stop_tool="create_draft")
    assert result == _call("create_draft", {"subject": "x"})
    assert len(provider.step_tools_seen) == 1


# --------------------------------------------------------------------------- unknown tool
def test_run_agent_unknown_tool_fed_back_as_error_then_stops():
    provider = FakeProvider([
        _reply([_call("not_a_real_tool")]),
        _reply([_call("create_draft")]),
    ])
    result = run_agent(provider, "sys", "user", tools=[], stop_tool="create_draft")
    assert result.name == "create_draft"
    assert len(provider.step_tools_seen) == 2
    _, _, is_error = provider.tool_result_calls[0]
    assert is_error is True


# --------------------------------------------------------------------------- registered executor
def test_run_agent_registered_executor_result_fed_back():
    def fake_check(call):
        return "plik OK"

    provider = FakeProvider([
        _reply([_call("check_print_file")]),
        _reply([_call("create_draft")]),
    ])
    result = run_agent(
        provider, "sys", "user", tools=[], stop_tool="create_draft",
        executors={"check_print_file": fake_check},
    )
    assert result.name == "create_draft"
    _, content, is_error = provider.tool_result_calls[0]
    assert content == "plik OK"
    assert is_error is False


def test_run_agent_executor_exception_caught_and_fed_back_as_error():
    def failing_check(call):
        raise RuntimeError("plik uszkodzony")

    provider = FakeProvider([
        _reply([_call("check_print_file")]),
        _reply([_call("create_draft")]),
    ])
    result = run_agent(
        provider, "sys", "user", tools=[], stop_tool="create_draft",
        executors={"check_print_file": failing_check},
    )
    assert result.name == "create_draft"
    _, content, is_error = provider.tool_result_calls[0]
    assert is_error is True
    assert "plik uszkodzony" in content


# --------------------------------------------------------------------------- no tool calls / limit
def test_run_agent_no_tool_calls_raises():
    provider = FakeProvider([_reply([], text="tylko tekst, nic nie wywołałem")])
    with pytest.raises(AgentDidNotActError):
        run_agent(provider, "sys", "user", tools=[], stop_tool="create_draft")


def test_run_agent_exceeds_max_turns_raises():
    provider = FakeProvider([_reply([_call("noop")]) for _ in range(MAX_TURNS)])
    with pytest.raises(AgentDidNotActError):
        run_agent(provider, "sys", "user", tools=[], stop_tool="create_draft")
    assert len(provider.step_tools_seen) == MAX_TURNS


# --------------------------------------------------------------------------- tools list stability
def test_run_agent_passes_full_tools_list_every_turn():
    from harness.src.agent.providers.base import ToolSpec
    tools = [ToolSpec(name="create_draft", description="d", input_schema={})]
    provider = FakeProvider([
        _reply([_call("noop")]),
        _reply([_call("create_draft")]),
    ])
    run_agent(provider, "sys", "user", tools=tools, stop_tool="create_draft")
    assert provider.step_tools_seen == [tools, tools]


# --------------------------------------------------------------------------- provider-boundary failures propagate
def test_run_agent_start_conversation_error_propagates():
    provider = FakeProvider([], start_conversation_error=ConnectionError("brak sieci"))
    with pytest.raises(ConnectionError):
        run_agent(provider, "sys", "user", tools=[], stop_tool="create_draft")


def test_run_agent_step_error_on_first_turn_propagates():
    provider = FakeProvider([TimeoutError("limit czasu API")])
    with pytest.raises(TimeoutError):
        run_agent(provider, "sys", "user", tools=[], stop_tool="create_draft")


def test_run_agent_step_error_on_second_turn_propagates():
    provider = FakeProvider([
        _reply([_call("check_print_file")]),
        TimeoutError("limit czasu API"),
    ])
    with pytest.raises(TimeoutError):
        run_agent(
            provider, "sys", "user", tools=[], stop_tool="create_draft",
            executors={"check_print_file": lambda call: "ok"},
        )


def test_run_agent_tool_result_messages_error_propagates():
    provider = FakeProvider(
        [_reply([_call("check_print_file")])],
        tool_result_error=RuntimeError("nie udało się zbudować wiadomości"),
    )
    with pytest.raises(RuntimeError):
        run_agent(
            provider, "sys", "user", tools=[], stop_tool="create_draft",
            executors={"check_print_file": lambda call: "ok"},
        )


# --------------------------------------------------------------------------- logging
def test_run_agent_logs_step_summary_per_turn(caplog):
    caplog.set_level(logging.INFO, logger="harness.agent_loop")
    provider = FakeProvider([
        _reply([_call("check_print_file")], text="sprawdzam plik"),
        _reply([_call("create_draft")]),
    ])
    run_agent(
        provider, "sys", "user", tools=[], stop_tool="create_draft",
        executors={"check_print_file": lambda call: "ok"},
    )
    assert "turn 1/" in caplog.text
    assert "check_print_file" in caplog.text
    assert "sprawdzam plik" in caplog.text
    assert "turn 2/" in caplog.text


def test_run_agent_logs_tool_execution_result_and_status(caplog):
    caplog.set_level(logging.INFO, logger="harness.agent_loop")
    provider = FakeProvider([
        _reply([_call("check_print_file")]),
        _reply([_call("create_draft")]),
    ])
    run_agent(
        provider, "sys", "user", tools=[], stop_tool="create_draft",
        executors={"check_print_file": lambda call: "spady OK"},
    )
    assert "spady OK" in caplog.text
    assert "OK" in caplog.text


def test_run_agent_logs_tool_failure_as_error(caplog):
    caplog.set_level(logging.INFO, logger="harness.agent_loop")
    provider = FakeProvider([
        _reply([_call("check_print_file")]),
        _reply([_call("create_draft")]),
    ])
    run_agent(
        provider, "sys", "user", tools=[], stop_tool="create_draft",
        executors={"check_print_file": lambda call: (_ for _ in ()).throw(RuntimeError("zły plik"))},
    )
    assert "ERROR" in caplog.text
    assert "zły plik" in caplog.text


def test_run_agent_logs_stop_tool_call(caplog):
    caplog.set_level(logging.INFO, logger="harness.agent_loop")
    provider = FakeProvider([_reply([_call("create_draft", id_="call_99")])])
    run_agent(provider, "sys", "user", tools=[], stop_tool="create_draft")
    assert "create_draft(id=call_99)" in caplog.text
    assert "stop_tool" in caplog.text


def test_run_agent_logs_truncate_long_text(caplog):
    caplog.set_level(logging.INFO, logger="harness.agent_loop")
    provider = FakeProvider([
        _reply([_call("create_draft")], text="x" * 1000),
    ])
    run_agent(provider, "sys", "user", tools=[], stop_tool="create_draft")
    assert "x" * 301 not in caplog.text
    assert "…" in caplog.text
