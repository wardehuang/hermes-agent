"""Fathom ensemble: merge, timeout skip, ChatGPT payload mapping."""

from __future__ import annotations

from plugins.web.fathom.chatgpt import rows_from_chatgpt
from plugins.web.fathom.common import AdapterOutcome, merge_rows, normalize_url
from plugins.web.fathom.provider import FathomWebSearchProvider


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
