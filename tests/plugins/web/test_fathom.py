"""Fathom ensemble: merge, timeout skip, ChatGPT payload mapping."""

from __future__ import annotations

import contextvars

from plugins.web.fathom import (
    SEARCH_DISPATCH_PROMPT,
    SEARCH_DISPATCH_SECTION_ID,
    register,
    search_dispatch_section,
)
from plugins.web.fathom.chatgpt import rows_from_chatgpt
from plugins.web.fathom.common import (
    AdapterOutcome,
    dispatch_adapters,
    merge_rows,
    normalize_url,
)
from plugins.web.fathom.provider import FathomWebSearchProvider


def test_dispatch_adapters_keeps_submitter_contextvars() -> None:
    seen = contextvars.ContextVar("fathom_scope_probe", default="missing")
    seen.set("bound")

    def make_call(name: str):
        def call() -> AdapterOutcome:
            value = seen.get()
            return AdapterOutcome(
                name=name,
                success=value == "bound",
                error="" if value == "bound" else value,
            )

        return call

    outcomes = dispatch_adapters(
        [("grok", 5.0, make_call("grok")), ("chatgpt", 5.0, make_call("chatgpt"))]
    )
    assert len(outcomes) == 2
    assert {item.name for item in outcomes} == {"grok", "chatgpt"}
    assert all(item.success for item in outcomes)


def test_merge_prefers_urls_seen_on_multiple_backends() -> None:
    outcomes = [
        AdapterOutcome(
            name="grok",
            success=True,
            rows=[
                {
                    "title": "Grok only",
                    "url": "https://a.example/one",
                    "description": "a",
                    "position": 1,
                },
                {
                    "title": "Shared",
                    "url": "https://b.example/two/",
                    "description": "from grok",
                    "position": 2,
                },
            ],
        ),
        AdapterOutcome(
            name="chatgpt",
            success=True,
            rows=[
                {
                    "title": "Shared chatgpt",
                    "url": "https://b.example/two",
                    "description": "",
                    "position": 1,
                },
                {
                    "title": "ChatGPT only",
                    "url": "https://c.example/three",
                    "description": "c",
                    "position": 2,
                },
            ],
        ),
    ]

    merged = merge_rows(outcomes, limit=5)
    assert normalize_url(merged[0]["url"]) == "https://b.example/two"
    assert merged[0]["backends"] == ["grok", "chatgpt"]
    assert merged[0]["title"] == "Shared"
    assert {normalize_url(row["url"]) for row in merged} == {
        "https://b.example/two",
        "https://a.example/one",
        "https://c.example/three",
    }


def test_merge_drops_timed_out_adapter() -> None:
    outcomes = [
        AdapterOutcome(
            name="grok",
            success=False,
            timed_out=True,
            error="grok timed out after 90s",
            rows=[
                {
                    "title": "Should drop",
                    "url": "https://drop.example/",
                    "description": "",
                    "position": 1,
                }
            ],
        ),
        AdapterOutcome(
            name="chatgpt",
            success=True,
            rows=[
                {
                    "title": "Keep",
                    "url": "https://keep.example/",
                    "description": "ok",
                    "position": 1,
                }
            ],
        ),
    ]

    merged = merge_rows(outcomes, limit=5)
    assert len(merged) == 1
    assert merged[0]["url"] == "https://keep.example/"
    assert merged[0]["backends"] == ["chatgpt"]


def test_merge_round_robins_unique_urls() -> None:
    grok_rows = [
        {
            "title": f"g{i}",
            "url": f"https://grok.example/{i}",
            "description": "",
            "position": i,
        }
        for i in range(1, 6)
    ]
    chatgpt_rows = [
        {
            "title": f"c{i}",
            "url": f"https://chatgpt.example/{i}",
            "description": "",
            "position": i,
        }
        for i in range(1, 6)
    ]
    merged = merge_rows(
        [
            AdapterOutcome(name="chatgpt", success=True, rows=chatgpt_rows),
            AdapterOutcome(name="grok", success=True, rows=grok_rows),
        ],
        limit=4,
    )
    backends = [row["backends"][0] for row in merged]
    assert backends.count("chatgpt") == 2
    assert backends.count("grok") == 2


def test_chatgpt_maps_sources_and_snippets() -> None:
    rows = rows_from_chatgpt(
        {
            "answer": "chatgpt2api turns ChatGPT into an API.",
            "sources": [
                {
                    "title": "GitHub",
                    "url": "https://github.com/example/chatgpt2api",
                    "snippet": "repo",
                },
                {"title": "PyPI", "url": "https://pypi.org/project/chatgpt2api/"},
            ],
        },
        limit=8,
    )
    assert len(rows) == 2
    assert rows[0]["description"] == "repo"
    assert rows[0]["position"] == 1
    assert rows[1]["url"] == "https://pypi.org/project/chatgpt2api/"


def test_assemble_keeps_fathom_badge_and_timeout_meta() -> None:
    assembled = FathomWebSearchProvider._assemble(
        [
            AdapterOutcome(
                name="grok",
                success=False,
                timed_out=True,
                error="grok timed out after 90s",
            ),
            AdapterOutcome(
                name="chatgpt",
                success=True,
                rows=[
                    {
                        "title": "Keep",
                        "url": "https://keep.example/",
                        "description": "ok",
                        "position": 1,
                    }
                ],
                extra={"answer": "short answer"},
            ),
        ],
        limit=5,
    )
    assert assembled["success"] is True
    assert assembled["data"]["provider"] == "fathom"
    assert assembled["data"]["provider_label"] == "Fathom"
    assert assembled["data"]["fathom"]["used"] == ["chatgpt"]
    assert assembled["data"]["fathom"]["timed_out"] == ["grok"]
    assert assembled["data"]["fathom"]["answers"]["chatgpt"] == "short answer"
    assert assembled["data"]["web"][0]["url"] == "https://keep.example/"


def test_assemble_all_timeout_is_error_with_badge() -> None:
    assembled = FathomWebSearchProvider._assemble(
        [
            AdapterOutcome(name="grok", success=False, timed_out=True, error="grok timed out"),
            AdapterOutcome(
                name="chatgpt", success=False, timed_out=True, error="chatgpt timed out"
            ),
        ],
        limit=5,
    )
    assert assembled["success"] is False
    assert "timed out" in assembled["error"]
    assert assembled["data"]["provider_label"] == "Fathom"
    assert assembled["data"]["web"] == []


class _FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name


def test_search_dispatch_prompt_allows_listed_search_name() -> None:
    assert "web_search" in SEARCH_DISPATCH_PROMPT
    assert "clientfn_web_search" in SEARCH_DISPATCH_PROMPT
    assert "execute_code" in SEARCH_DISPATCH_PROMPT
    assert "type=web_search" in SEARCH_DISPATCH_PROMPT
    assert "Do not invoke clientfn_web_search" not in SEARCH_DISPATCH_PROMPT


def test_search_dispatch_section_only_when_fathom_active(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.web_search_registry.get_active_search_provider",
        lambda: _FakeProvider("fathom"),
    )
    assert search_dispatch_section({}) == SEARCH_DISPATCH_PROMPT

    monkeypatch.setattr(
        "agent.web_search_registry.get_active_search_provider",
        lambda: _FakeProvider("firecrawl"),
    )
    assert search_dispatch_section({}) == ""

    monkeypatch.setattr(
        "agent.web_search_registry.get_active_search_provider",
        lambda: None,
    )
    assert search_dispatch_section({}) == ""


def test_register_adds_search_dispatch_prompt_section() -> None:
    recorded: list[tuple] = []

    class _Ctx:
        def register_web_search_provider(self, provider) -> None:
            recorded.append(("provider", type(provider).__name__))

        def register_system_prompt_section(self, section_id, content, **kwargs) -> None:
            recorded.append(("section", section_id, content, kwargs))

    register(_Ctx())
    assert recorded[0] == ("provider", "FathomWebSearchProvider")
    assert recorded[1][0] == "section"
    assert recorded[1][1] == SEARCH_DISPATCH_SECTION_ID
    assert recorded[1][2] is search_dispatch_section
    assert recorded[1][3]["position"] == "after_memory"
    assert recorded[1][3]["max_chars"] == 800


def test_chatgpt_search_sends_default_effort(monkeypatch) -> None:
    from plugins.web.fathom.chatgpt import ChatGPTAdapter

    monkeypatch.setattr(
        "plugins.web.fathom.chatgpt.get_provider_env",
        lambda name: "test-key" if name == "CHATGPT_SEARCH_API_KEY" else "",
    )
    monkeypatch.setattr("plugins.web.fathom.chatgpt.load_config_section", lambda _path: {})
    captured: dict = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"sources": [], "answer": ""}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    outcome = ChatGPTAdapter().search("query", 3)
    assert outcome.success is True
    assert captured["json"] == {
        "prompt": "query",
        "model": "gpt-5-6-thinking",
        "reasoning_effort": "extended",
        "thinking_effort": "extended",
    }


def test_chatgpt_effort_env_beats_config(monkeypatch) -> None:
    from plugins.web.fathom.chatgpt import ChatGPTAdapter

    def env(name: str) -> str:
        if name == "CHATGPT_SEARCH_EFFORT":
            return "standard"
        return ""

    monkeypatch.setattr("plugins.web.fathom.chatgpt.get_provider_env", env)
    monkeypatch.setattr(
        "plugins.web.fathom.chatgpt.load_config_section",
        lambda path: {"chatgpt": {"effort": "max"}} if path == ("web", "fathom") else {},
    )
    assert ChatGPTAdapter().load_settings()["effort"] == "standard"


def test_chatgpt_effort_from_config(monkeypatch) -> None:
    from plugins.web.fathom.chatgpt import ChatGPTAdapter

    monkeypatch.setattr("plugins.web.fathom.chatgpt.get_provider_env", lambda _name: "")
    monkeypatch.setattr(
        "plugins.web.fathom.chatgpt.load_config_section",
        lambda path: {"chatgpt": {"effort": "max"}} if path == ("web", "fathom") else {},
    )
    assert ChatGPTAdapter().load_settings()["effort"] == "max"


def test_chatgpt_invalid_effort_is_error(monkeypatch) -> None:
    from plugins.web.fathom.chatgpt import ChatGPTAdapter

    monkeypatch.setattr(
        "plugins.web.fathom.chatgpt.get_provider_env",
        lambda name: {
            "CHATGPT_SEARCH_EFFORT": "nope",
            "CHATGPT_SEARCH_API_KEY": "test-key",
        }.get(name, ""),
    )
    monkeypatch.setattr("plugins.web.fathom.chatgpt.load_config_section", lambda _path: {})
    outcome = ChatGPTAdapter().search("query", 3)
    assert outcome.success is False
    assert "effort" in outcome.error


def test_setup_schema_exposes_chatgpt_effort() -> None:
    schema = FathomWebSearchProvider().get_setup_schema()
    effort = next(item for item in schema["env_vars"] if item["key"] == "CHATGPT_SEARCH_EFFORT")
    assert effort["default"] == "extended"
    assert "standard|max|extended" in effort["prompt"]
