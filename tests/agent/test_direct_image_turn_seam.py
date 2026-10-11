"""The turn loop's wiring must survive a merge resolution untouched.

Two spots in ``agent/conversation_loop._run_conversation_turn`` were hand-written during the
``Merge tag 'v0.21.6' into my-feature`` resolution and referenced names that exist nowhere:

* the create-image panel's direct-send call used pre-refactor loop locals
  (``NameError: name 'original_user_message' is not defined``), which every gateway turn hit;
* the loop head's guard used an invented state attribute (``s.api_max_total`` —
  ``'_LoopState' object has no attribute 'api_max_total'``), which every ordinary turn hit once the
  first was fixed.

``tests/tools/test_create_image_direct_send.py`` covers the direct-send helper alone and no test
touched the loop head, so both stayed invisible to the suite.
"""

from __future__ import annotations

import json
from types import SimpleNamespace


class _FakeCompletions:
    def __init__(self):
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="main model answered", reasoning=None, tool_calls=[]),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def _panel_cache(tmp_path, monkeypatch):
    """Point the panel file lookup at a temp home and return its ``cache`` directory."""
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    return cache


def _agent(monkeypatch, client):
    from run_agent import AIAgent

    monkeypatch.setattr("agent.process_bootstrap.OpenAI", lambda **_kw: client)
    monkeypatch.setattr("model_tools.get_tool_definitions", lambda *a, **k: [])
    return AIAgent(
        model="gpt-5",
        api_key="test-key",
        base_url="acp://somevendor",
        platform="cli",
        max_iterations=2,
        quiet_mode=True,
        skip_memory=True,
    )


def test_panel_direct_send_skips_the_main_model(tmp_path, monkeypatch):
    prompt = "a cat by the window"
    cache = _panel_cache(tmp_path, monkeypatch)
    (cache / "create_image_panel.json").write_text(
        json.dumps({"active": True, "direct": True, "prompt": prompt}), encoding="utf-8"
    )

    client = _FakeClient()
    agent = _agent(monkeypatch, client)
    agent.valid_tool_names = {"image_generate"}
    executed: dict = {}

    def _execute_tool_calls(assistant_message, messages, task_id, api_call_count):
        call = assistant_message.tool_calls[0]
        executed["name"] = call.function.name
        executed["args"] = json.loads(call.function.arguments)
        messages.append(
            {
                "role": "tool",
                "name": call.function.name,
                "tool_call_id": call.id,
                "content": json.dumps({"success": True, "image": "/tmp/out.png"}),
            }
        )

    monkeypatch.setattr(agent, "_execute_tool_calls", _execute_tool_calls)

    result = agent.run_conversation(prompt)

    assert result["completed"] is True
    assert result["final_response"] == "已生成。"
    assert executed["name"] == "image_generate"
    assert executed["args"] == {"prompt": prompt}
    # The image card is the tool row, so the transcript must carry one.
    assert any(m.get("name") == "image_generate" for m in result["messages"])
    assert client.chat.completions.calls == [], "the panel-direct turn reached the provider"


def test_ordinary_turn_still_enters_the_provider_loop(tmp_path, monkeypatch):
    """No panel file: the turn must reach the provider through the loop head's budget guard."""
    _panel_cache(tmp_path, monkeypatch)

    client = _FakeClient()
    agent = _agent(monkeypatch, client)

    result = agent.run_conversation("hello there")

    assert result["completed"] is True
    assert result["final_response"] == "main model answered"
    assert len(client.chat.completions.calls) == 1
