"""One-shot create-image panel send: skip the main model."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.direct_image_generate import maybe_run_direct_image_generate
from tools.image_generation_tool import consume_panel_direct_call


@pytest.fixture
def panel_home(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(
        "hermes_cli.config.get_hermes_home",
        lambda: tmp_path,
    )
    return tmp_path


def _write_panel(home, **fields):
    payload = {
        "active": True,
        "direct": True,
        "prompt": "a cat by the window",
        "params": {"size": "1024x1024"},
        "provider": "chatgpt2api",
        "model": "gpt-image-2",
    }
    payload.update(fields)
    path = home / "cache" / "create_image_panel.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_consume_returns_args_and_clears_direct(panel_home):
    _write_panel(
        panel_home,
        image_url="C:/tmp/src.png",
        params={"size": "1024x1024", "background": "transparent", "n": 2, "quality": "high"},
    )
    args = consume_panel_direct_call(user_prompt="a cat by the window")
    assert args == {
        "prompt": "a cat by the window",
        "image_url": "C:/tmp/src.png",
        "size": "1024x1024",
        "background": "transparent",
        "n": 2,
        "quality": "high",
    }
    data = json.loads((panel_home / "cache" / "create_image_panel.json").read_text(encoding="utf-8"))
    assert data["direct"] is False
    assert data["active"] is True
    assert consume_panel_direct_call(user_prompt="a cat by the window") is None


def test_consume_stale_prompt_clears_direct_without_firing(panel_home):
    _write_panel(panel_home, prompt="draw a cat")
    assert consume_panel_direct_call(user_prompt="hello") is None
    data = json.loads((panel_home / "cache" / "create_image_panel.json").read_text(encoding="utf-8"))
    assert data["direct"] is False


def test_consume_inactive_or_not_direct(panel_home):
    _write_panel(panel_home, active=False)
    assert consume_panel_direct_call(user_prompt="a cat by the window") is None
    _write_panel(panel_home, direct=False)
    assert consume_panel_direct_call(user_prompt="a cat by the window") is None


def test_maybe_run_injects_tool_and_skips_when_direct(panel_home):
    _write_panel(panel_home)
    executed = {}

    class Agent:
        valid_tool_names = {"image_generate"}

        def _build_assistant_message(self, assistant_message, finish_reason):
            tc = assistant_message.tool_calls[0]
            return {
                "role": "assistant",
                "content": "",
                "finish_reason": finish_reason,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                ],
            }

        def _persist_session(self, messages, conversation_history):
            return True

        def _execute_tool_calls(self, assistant_message, messages, task_id, api_call_count):
            executed["name"] = assistant_message.tool_calls[0].function.name
            executed["args"] = json.loads(assistant_message.tool_calls[0].function.arguments)
            messages.append(
                {
                    "role": "tool",
                    "name": "image_generate",
                    "tool_call_id": assistant_message.tool_calls[0].id,
                    "content": json.dumps({"success": True, "image": "/tmp/out.png"}),
                }
            )

    messages = [{"role": "user", "content": "a cat by the window"}]
    result = maybe_run_direct_image_generate(
        Agent(),
        messages,
        effective_task_id="sess-1",
        conversation_history=[],
        user_message="a cat by the window",
    )
    assert result == "已生成。"
    assert executed["name"] == "image_generate"
    assert executed["args"]["prompt"] == "a cat by the window"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "image_generate"
    assert messages[2]["role"] == "tool"


def test_maybe_run_noop_without_direct_flag(panel_home):
    _write_panel(panel_home, direct=False)
    agent = SimpleNamespace(valid_tool_names={"image_generate"})
    messages = [{"role": "user", "content": "hello"}]
    assert (
        maybe_run_direct_image_generate(
            agent,
            messages,
            effective_task_id="sess-1",
            user_message="hello",
        )
        is None
    )
    assert messages == [{"role": "user", "content": "hello"}]


def test_maybe_run_force_tool_prompt_fallback(panel_home):
    _write_panel(panel_home, direct=False)
    executed = {}

    class Agent:
        valid_tool_names = {"image_generate"}

        def _build_assistant_message(self, assistant_message, finish_reason):
            tc = assistant_message.tool_calls[0]
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                ],
            }

        def _persist_session(self, messages, conversation_history):
            return True

        def _execute_tool_calls(self, assistant_message, messages, task_id, api_call_count):
            executed["args"] = json.loads(assistant_message.tool_calls[0].function.arguments)
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps({"success": True, "image": "/tmp/out.png"}),
                }
            )

    prompt = (
        "Call the image_generate tool exactly once with these JSON arguments.\n"
        "```json\n"
        '{"prompt": "a cat by the window", "size": "1024x1024"}\n'
        "```"
    )
    messages = [{"role": "user", "content": prompt}]
    result = maybe_run_direct_image_generate(
        Agent(),
        messages,
        effective_task_id="sess-1",
        conversation_history=[],
        user_message=prompt,
    )
    assert result == "已生成。"
    assert executed["args"]["prompt"] == "a cat by the window"
