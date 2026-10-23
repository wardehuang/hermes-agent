"""Fathom ensemble: merge, timeout skip, ChatGPT payload mapping."""

from __future__ import annotations

import contextvars
import json

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
    assert merged[0]["description"] == "from grok"
    assert merged[0]["snippets"] == [{"backend": "grok", "text": "from grok"}]
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


def test_merge_keeps_every_backend_snippet() -> None:
    merged = merge_rows(
        [
            AdapterOutcome(
                name="grok",
                success=True,
                rows=[
                    {
                        "title": "Shared",
                        "url": "https://b.example/two",
                        "description": "grok said Tuesday",
                        "position": 1,
                    }
                ],
            ),
            AdapterOutcome(
                name="tavily",
                success=True,
                rows=[
                    {
                        "title": "Shared",
                        "url": "https://b.example/two/",
                        "description": "tavily said Wednesday",
                        "position": 1,
                    }
                ],
            ),
        ],
        limit=5,
    )
    assert merged[0]["snippets"] == [
        {"backend": "grok", "text": "grok said Tuesday"},
        {"backend": "tavily", "text": "tavily said Wednesday"},
    ]
    assert "[grok] grok said Tuesday" in merged[0]["description"]
    assert "[tavily] tavily said Wednesday" in merged[0]["description"]


def test_adjudicate_emits_one_answer_and_keeps_conflicts() -> None:
    from plugins.web.fathom.judge import adjudicate

    calls: list[str] = []

    def complete(messages):
        system = messages[0]["content"]
        calls.append(system)
        if system.startswith("You rank"):
            return (
                json.dumps(
                    {
                        "order": [
                            "https://keep.example/a",
                            "https://drop.example/b",
                        ],
                        "read": ["https://keep.example/a"],
                    }
                ),
                "session-main",
            )
        return (
            json.dumps(
                {
                    "answer": "The page says Tuesday.",
                    "results": [
                        {
                            "url": "https://keep.example/a",
                            "description": "Page says Tuesday.",
                        }
                    ],
                    "conflicts": [
                        {
                            "point": "which day",
                            "sides": [
                                {"claim": "Tuesday", "url": "https://keep.example/a"},
                                {"claim": "Wednesday", "url": "https://other.example/c"},
                                {
                                    "claim": "invented",
                                    "url": "https://invented.example/nope",
                                },
                            ],
                        }
                    ],
                }
            ),
            "session-main",
        )

    def extract(urls):
        assert urls == ["https://keep.example/a"]
        return [
            {
                "url": urls[0],
                "title": "Keep",
                "content": "The event is on Tuesday.",
            }
        ]

    outcomes = [
        AdapterOutcome(
            name="chatgpt",
            success=True,
            rows=[
                {
                    "title": "Off topic",
                    "url": "https://drop.example/b",
                    "description": "unrelated",
                    "position": 1,
                },
                {
                    "title": "Keep",
                    "url": "https://keep.example/a",
                    "description": "snippet tuesday",
                    "position": 2,
                },
            ],
            extra={"answer": "maybe Wednesday"},
        ),
        AdapterOutcome(
            name="tavily",
            success=True,
            rows=[
                {
                    "title": "Other",
                    "url": "https://other.example/c",
                    "description": "snippet wednesday",
                    "position": 1,
                }
            ],
            extra={"answer": "maybe Tuesday"},
        ),
    ]
    result = adjudicate(
        None,
        "which day",
        outcomes,
        2,
        complete=complete,
        extract=extract,
    )
    assert result.error == ""
    payload = result.response
    assert payload["success"] is True
    assert [row["url"] for row in payload["data"]["web"]] == [
        "https://keep.example/a",
        "https://drop.example/b",
    ]
    assert payload["data"]["web"][0]["description"] == "Page says Tuesday."
    assert payload["data"]["fathom"]["answer"] == "The page says Tuesday."
    assert "answers" not in payload["data"]["fathom"]
    assert payload["data"]["fathom"]["conflicts"] == [
        {
            "point": "which day",
            "sides": [
                {"claim": "Tuesday", "url": "https://keep.example/a"},
                {"claim": "Wednesday", "url": "https://other.example/c"},
            ],
        }
    ]
    assert payload["data"]["fathom"]["judge"]["fallback"] is None
    assert payload["data"]["fathom"]["judge"]["model"] == "session-main"
    assert len(calls) == 2


def test_adjudicate_bad_rank_returns_no_response() -> None:
    from plugins.web.fathom.judge import adjudicate

    result = adjudicate(
        None,
        "query",
        [
            AdapterOutcome(
                name="grok",
                success=True,
                rows=[
                    {
                        "title": "Keep",
                        "url": "https://keep.example/",
                        "description": "ok",
                        "position": 1,
                    }
                ],
            )
        ],
        5,
        complete=lambda _messages: ("not json", "session-main"),
        extract=lambda _urls: [],
    )
    assert result.response is None
    assert "JSON" in result.error


def test_raise_request_count_respects_floor_and_cap() -> None:
    from plugins.web.fathom.common import raise_request_count

    body = {"numResults": 30}
    raise_request_count(body, "numResults", 20, 100)
    assert body["numResults"] == 30
    body = {"numResults": 10}
    raise_request_count(body, "numResults", 20, 100)
    assert body["numResults"] == 20
    body = {"max_results": 10}
    raise_request_count(body, "max_results", 50, 20)
    assert body["max_results"] == 20


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


def test_assemble_keeps_timeout_meta() -> None:
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
    assert "provider_label" not in assembled["data"]
    assert assembled["data"]["fathom"]["used"] == ["chatgpt"]
    assert assembled["data"]["fathom"]["timed_out"] == ["grok"]
    assert "answers" not in assembled["data"]["fathom"]
    assert assembled["data"]["web"][0]["url"] == "https://keep.example/"
    assert assembled["data"]["web"][0]["snippets"] == [
        {"backend": "chatgpt", "text": "ok"}
    ]


def test_assemble_all_timeout_is_error() -> None:
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
    assert "provider_label" not in assembled["data"]
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


def test_chatgpt_search_sends_configured_effort(monkeypatch) -> None:
    from plugins.web.fathom.chatgpt import ChatGPTAdapter

    def env(name: str) -> str:
        return {
            "CHATGPT_SEARCH_API_KEY": "test-key",
            "CHATGPT_SEARCH_BASE_URL": "http://chatgpt.example/v1",
            "CHATGPT_SEARCH_MODEL": "gpt-5-6-thinking",
            "CHATGPT_SEARCH_EFFORT": "extended",
        }.get(name, "")

    monkeypatch.setattr("plugins.web.fathom.chatgpt.get_provider_env", env)
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
            "CHATGPT_SEARCH_BASE_URL": "http://chatgpt.example/v1",
            "CHATGPT_SEARCH_MODEL": "gpt-5-6-thinking",
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


_EXA_ENV = {
    "EXA_SEARCH_API_KEY": "exa-key",
    "EXA_SEARCH_BASE_URL": "http://wcpap.edmundvps.site:19881",
    "EXA_SEARCH_DEFAULTS": '{"type":"deep-reasoning","numResults":10,"contents":{"highlights":true}}',
    "EXA_EXTRACT_DEFAULTS": '{"text":true,"highlights":true}',
}


def _exa_env(monkeypatch, **overrides: str) -> None:
    values = dict(_EXA_ENV)
    values.update(overrides)

    def read(name: str) -> str | None:
        if name in values:
            return values[name]
        return None

    monkeypatch.setattr("plugins.web.fathom.exa.read_env", read)
    monkeypatch.setattr("plugins.web.fathom.common.read_env", read)
    monkeypatch.setattr("plugins.web.fathom.exa.get_provider_env", lambda name: values.get(name, "") or "")
    monkeypatch.setattr("plugins.web.fathom.exa.load_config_section", lambda _path: {})


def test_exa_rows_use_highlights_then_stop_at_limit() -> None:
    from plugins.web.fathom.exa import rows_from_exa

    rows = rows_from_exa(
        {
            "results": [
                {
                    "title": "First",
                    "url": "https://a.example",
                    "highlights": ["one", "two"],
                },
                {"title": "Second", "url": "https://b.example", "text": "body"},
            ]
        },
        limit=1,
    )
    assert rows == [
        {
            "title": "First",
            "url": "https://a.example",
            "description": "one two",
            "position": 1,
        }
    ]


def test_exa_search_sends_configured_body(monkeypatch) -> None:
    from plugins.web.fathom.exa import ExaAdapter

    _exa_env(monkeypatch)
    captured: dict = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {
                        "title": "Hit",
                        "url": "https://a.example",
                        "highlights": ["snip"],
                    },
                    {
                        "title": "Dropped",
                        "url": "https://b.example",
                        "highlights": ["nope"],
                    },
                ]
            }

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    outcome = ExaAdapter().search("latest ai search apis", 1)
    assert outcome.success is True
    assert captured["url"] == "http://wcpap.edmundvps.site:19881/search"
    assert captured["headers"]["Authorization"] == "Bearer exa-key"
    assert captured["json"] == {
        "type": "deep-reasoning",
        "numResults": 10,
        "contents": {"highlights": True},
        "query": "latest ai search apis",
    }
    assert [row["url"] for row in outcome.rows] == ["https://a.example"]


def test_exa_search_defaults_env_overrides_type(monkeypatch) -> None:
    from plugins.web.fathom.exa import ExaAdapter

    def read(name: str) -> str | None:
        if name == "EXA_SEARCH_DEFAULTS":
            return '{"type":"fast","numResults":3,"contents":{"highlights":true}}'
        return None

    monkeypatch.setattr("plugins.web.fathom.exa.read_env", read)
    monkeypatch.setattr("plugins.web.fathom.exa.load_config_section", lambda _path: {})
    assert ExaAdapter().search_body() == {
        "type": "fast",
        "numResults": 3,
        "contents": {"highlights": True},
    }


def test_exa_invalid_search_type_is_error(monkeypatch) -> None:
    from plugins.web.fathom.exa import ExaAdapter

    _exa_env(
        monkeypatch,
        EXA_SEARCH_DEFAULTS='{"type":"nope"}',
    )
    outcome = ExaAdapter().search("query", 3)
    assert outcome.success is False
    assert "type" in outcome.error


def test_exa_extract_maps_text_highlights_and_status(monkeypatch) -> None:
    from plugins.web.fathom.exa import ExaAdapter

    _exa_env(monkeypatch)
    captured: dict = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {
                        "url": "https://exa.ai",
                        "title": "Exa",
                        "text": "body",
                        "highlights": ["snip"],
                    }
                ],
                "statuses": [
                    {"id": "https://exa.ai", "status": "success"},
                    {
                        "id": "https://missing.example",
                        "status": "error",
                        "error": {"tag": "CRAWL_NOT_FOUND", "httpStatusCode": 404},
                    },
                ],
            }

    def fake_post(url, headers, json, timeout):
        del headers, timeout
        captured["url"] = url
        captured["json"] = json
        return _Response()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    pages = ExaAdapter().extract(["https://exa.ai", "https://missing.example"])
    assert captured["url"] == "http://wcpap.edmundvps.site:19881/contents"
    assert captured["json"] == {
        "text": True,
        "highlights": True,
        "urls": ["https://exa.ai", "https://missing.example"],
    }
    assert pages[0]["url"] == "https://exa.ai"
    assert pages[0]["title"] == "Exa"
    assert pages[0]["content"] == "body\n\nsnip"
    assert pages[0]["raw_content"] == "body\n\nsnip"
    assert pages[0]["metadata"]["sourceURL"] == "https://exa.ai"
    assert pages[1]["url"] == "https://missing.example"
    assert pages[1]["error"] == "CRAWL_NOT_FOUND (404)"


def test_exa_incomplete_extract_does_not_call_http(monkeypatch) -> None:
    from plugins.web.fathom.exa import ExaAdapter

    def read(name: str) -> str | None:
        if name == "EXA_SEARCH_API_KEY":
            return "   "
        return None

    monkeypatch.setattr("plugins.web.fathom.exa.read_env", read)
    monkeypatch.setattr("plugins.web.fathom.common.read_env", read)
    monkeypatch.setattr("plugins.web.fathom.exa.load_config_section", lambda _path: {})

    def fail_post(*_args, **_kwargs):
        raise AssertionError("httpx.post should not be called")

    import httpx

    monkeypatch.setattr(httpx, "post", fail_post)
    adapter = ExaAdapter()
    assert adapter.enabled() is False
    pages = adapter.extract(["https://exa.ai"])
    assert pages[0]["error"] == "Exa skipped because an input is empty."


def test_setup_schema_lists_inputs_without_toggles() -> None:
    from plugins.web.fathom.exa import (
        DEFAULT_API_KEY,
        DEFAULT_EXTRACT_DEFAULTS,
        DEFAULT_SEARCH_DEFAULTS,
    )

    schema = FathomWebSearchProvider().get_setup_schema()
    by_key = {item["key"]: item for item in schema["env_vars"]}
    assert "GROK_SEARCH_API_KEY" not in by_key
    assert "EXA_SEARCH_ENABLED" not in by_key
    assert "CHATGPT_SEARCH_ENABLED" not in by_key
    assert "TAVILY_SEARCH_ENABLED" not in by_key
    assert by_key["EXA_SEARCH_API_KEY"]["default"] == DEFAULT_API_KEY
    assert by_key["TAVILY_SEARCH_API_KEY"]["default"] == DEFAULT_API_KEY
    assert "group" not in by_key["EXA_SEARCH_BASE_URL"]
    assert "controls_group" not in by_key["EXA_SEARCH_BASE_URL"]
    assert "type" not in by_key["EXA_SEARCH_BASE_URL"]
    assert by_key["EXA_SEARCH_BASE_URL"]["default"] == "http://wcpap.edmundvps.site:19881"
    assert by_key["EXA_SEARCH_DEFAULTS"]["default"] == DEFAULT_SEARCH_DEFAULTS
    assert by_key["EXA_EXTRACT_DEFAULTS"]["default"] == DEFAULT_EXTRACT_DEFAULTS
    assert by_key["CHATGPT_SEARCH_EFFORT"]["default"] == "extended"
    assert FathomWebSearchProvider().supports_extract() is True
