"""Fathom — multi-provider web search.

Live adapters: Grok (Responses API), ChatGPT (chatgpt2api ``/v1/search``),
and Exa (FreeAPI ``POST /search`` plus ``POST /contents`` for extract).
Tavily lands next.

Each adapter has its own timeout (default 120s). A timed-out adapter is
dropped for that call; remaining adapters still contribute.

Config::

    web:
      search_backend: "fathom"
      fathom:
        timeout: 120
        base_url: "http://wcpa.edmundvps.site:18453/v1"
        model: "grok-4.20-multi-agent-0309"
        effort: "high"
        enable_web_search: true
        enable_x_search: false
        grok_enabled: true
        key_env: "GROK2API_API_KEY"
        chatgpt:
          enabled: true
          base_url: "http://wcpa.edmundvps.site:3000/v1"
          model: "gpt-5-6-thinking"
          effort: "extended"
          timeout: 120
          key_env: "CHATGPT2API_API_KEY"
        exa:
          enabled: true
          base_url: "http://wcpap.edmundvps.site:19881"
          search_defaults:
            type: deep-reasoning
            numResults: 10
            contents:
              highlights: true
          extract_defaults:
            text: true
            highlights: true

Env overrides (Desktop Tools panel can write these):

    GROK_SEARCH_API_KEY
    GROK_SEARCH_BASE_URL
    GROK_SEARCH_MODEL
    GROK_SEARCH_EFFORT
    GROK_SEARCH_TIMEOUT
    GROK_SEARCH_ENABLED
    GROK_SEARCH_ENABLE_X_SEARCH
    CHATGPT_SEARCH_API_KEY
    CHATGPT_SEARCH_BASE_URL
    CHATGPT_SEARCH_MODEL
    CHATGPT_SEARCH_EFFORT
    CHATGPT_SEARCH_TIMEOUT
    CHATGPT_SEARCH_ENABLED
    EXA_SEARCH_ENABLED
    EXA_SEARCH_API_KEY
    EXA_SEARCH_BASE_URL
    EXA_SEARCH_DEFAULTS
    EXA_EXTRACT_DEFAULTS
    EXA_SEARCH_TIMEOUT
    FATHOM_TIMEOUT

If adapter base_url / API key are unset, Fathom reuses
``providers.grok2api`` and ``providers.chatgpt2api``.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.web_search_provider import WebSearchProvider

from plugins.web.fathom.chatgpt import ChatGPTAdapter, DEFAULT_BASE_URL as CHATGPT_DEFAULT_BASE_URL
from plugins.web.fathom.chatgpt import DEFAULT_EFFORT as CHATGPT_DEFAULT_EFFORT
from plugins.web.fathom.chatgpt import DEFAULT_MODEL as CHATGPT_DEFAULT_MODEL
from plugins.web.fathom.common import (
    AdapterOutcome,
    DEFAULT_PROVIDER_TIMEOUT,
    PROVIDER_LABEL,
    dispatch_adapters,
    merge_rows,
)
from plugins.web.fathom.exa import (
    DEFAULT_API_KEY as EXA_DEFAULT_API_KEY,
    DEFAULT_BASE_URL as EXA_DEFAULT_BASE_URL,
    DEFAULT_EXTRACT_DEFAULTS,
    DEFAULT_SEARCH_DEFAULTS,
    ExaAdapter,
)
from plugins.web.fathom.grok import DEFAULT_BASE_URL as GROK_DEFAULT_BASE_URL
from plugins.web.fathom.grok import DEFAULT_EFFORT, DEFAULT_MODEL as GROK_DEFAULT_MODEL
from plugins.web.fathom.grok import GrokAdapter

logger = logging.getLogger(__name__)


class FathomWebSearchProvider(WebSearchProvider):
    """Ensemble search backend. Grok, ChatGPT, and Exa run in parallel."""

    def __init__(self) -> None:
        self._grok = GrokAdapter()
        self._chatgpt = ChatGPTAdapter()
        self._exa = ExaAdapter()

    def _adapters(self):
        return (self._grok, self._chatgpt, self._exa)

    @property
    def name(self) -> str:
        return "fathom"

    @property
    def display_name(self) -> str:
        return PROVIDER_LABEL

    def is_available(self) -> bool:
        return any(adapter.is_available() for adapter in self._adapters())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            "name": PROVIDER_LABEL,
            "badge": "ensemble",
            "tag": (
                "Multi-provider web search. Grok, ChatGPT, and Exa run in parallel; "
                "a 120s timeout drops that adapter for the call. "
                "Exa also extracts page content. Tavily comes next."
            ),
            "env_vars": [
                {
                    "key": "GROK_SEARCH_ENABLED",
                    "prompt": "Grok",
                    "type": "bool",
                    "default": True,
                    "controls_group": "grok",
                },
                {
                    "key": "GROK_SEARCH_API_KEY",
                    "prompt": "Grok API key. Unset uses GROK2API_API_KEY.",
                    "fallback_key": "GROK2API_API_KEY",
                    "group": "grok",
                },
                {
                    "key": "GROK_SEARCH_BASE_URL",
                    "prompt": "Grok Responses API base URL",
                    "default": GROK_DEFAULT_BASE_URL,
                    "group": "grok",
                },
                {
                    "key": "GROK_SEARCH_MODEL",
                    "prompt": "Grok model id",
                    "default": GROK_DEFAULT_MODEL,
                    "group": "grok",
                },
                {
                    "key": "GROK_SEARCH_EFFORT",
                    "prompt": "Grok reasoning.effort: low|medium|high|xhigh (high = 16 agents)",
                    "default": DEFAULT_EFFORT,
                    "group": "grok",
                },
                {
                    "key": "GROK_SEARCH_ENABLE_X_SEARCH",
                    "prompt": "X search",
                    "type": "bool",
                    "default": False,
                    "group": "grok",
                },
                {
                    "key": "CHATGPT_SEARCH_ENABLED",
                    "prompt": "ChatGPT",
                    "type": "bool",
                    "default": True,
                    "controls_group": "chatgpt",
                },
                {
                    "key": "CHATGPT_SEARCH_API_KEY",
                    "prompt": "ChatGPT search API key. Unset uses CHATGPT2API_API_KEY.",
                    "fallback_key": "CHATGPT2API_API_KEY",
                    "group": "chatgpt",
                },
                {
                    "key": "CHATGPT_SEARCH_BASE_URL",
                    "prompt": "ChatGPT /v1/search base URL",
                    "default": CHATGPT_DEFAULT_BASE_URL,
                    "group": "chatgpt",
                },
                {
                    "key": "CHATGPT_SEARCH_MODEL",
                    "prompt": "ChatGPT search model",
                    "default": CHATGPT_DEFAULT_MODEL,
                    "group": "chatgpt",
                },
                {
                    "key": "CHATGPT_SEARCH_EFFORT",
                    "prompt": (
                        "ChatGPT reasoning_effort and thinking_effort: "
                        "standard|max|extended"
                    ),
                    "default": CHATGPT_DEFAULT_EFFORT,
                    "group": "chatgpt",
                },
                {
                    "key": "EXA_SEARCH_ENABLED",
                    "prompt": "Exa",
                    "type": "bool",
                    "default": True,
                    "controls_group": "exa",
                },
                {
                    "key": "EXA_SEARCH_API_KEY",
                    "prompt": "Exa API key. Unset uses the built-in FreeAPI default.",
                    "default": EXA_DEFAULT_API_KEY,
                    "group": "exa",
                },
                {
                    "key": "EXA_SEARCH_BASE_URL",
                    "prompt": "Exa base URL. Search is POST /search; extract is POST /contents.",
                    "default": EXA_DEFAULT_BASE_URL,
                    "group": "exa",
                },
                {
                    "key": "EXA_SEARCH_DEFAULTS",
                    "prompt": (
                        "Exa POST /search JSON defaults. query is set per call. "
                        "numResults is the Exa request size; the tool limit still "
                        "caps this adapter's rows."
                    ),
                    "default": DEFAULT_SEARCH_DEFAULTS,
                    "group": "exa",
                },
                {
                    "key": "EXA_EXTRACT_DEFAULTS",
                    "prompt": "Exa POST /contents JSON defaults. urls is set per call.",
                    "default": DEFAULT_EXTRACT_DEFAULTS,
                    "group": "exa",
                },
            ],
        }

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return {"success": False, "error": "Interrupted"}
        except Exception:
            pass

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 100))

        jobs = self._jobs(query, limit)
        if not jobs:
            enabled = [adapter for adapter in self._adapters() if adapter.enabled()]
            if not enabled:
                return {
                    "success": False,
                    "error": "No Fathom providers enabled. Turn on Grok, ChatGPT, and/or Exa.",
                }
            return {
                "success": False,
                "error": (
                    "No Fathom credentials. Set GROK_SEARCH_API_KEY / "
                    "GROK2API_API_KEY, CHATGPT_SEARCH_API_KEY / "
                    "CHATGPT2API_API_KEY, or EXA_SEARCH_API_KEY."
                ),
            }

        logger.info(
            "Fathom ensemble query=%r limit=%d adapters=%s",
            query,
            limit,
            [name for name, _timeout, _call in jobs],
        )
        outcomes = dispatch_adapters(jobs)
        return self._assemble(outcomes, limit)

    def _jobs(self, query: str, limit: int):
        jobs = []
        for adapter in self._adapters():
            if not adapter.is_available():
                continue
            try:
                timeout = adapter.timeout()
            except ValueError as exc:
                logger.warning("Fathom adapter %s config error: %s", adapter.name, exc)
                jobs.append(
                    (
                        adapter.name,
                        DEFAULT_PROVIDER_TIMEOUT,
                        lambda error=str(exc), name=adapter.name: AdapterOutcome(
                            name=name, success=False, error=error
                        ),
                    )
                )
                continue
            jobs.append(
                (
                    adapter.name,
                    timeout,
                    lambda current=adapter: current.search(query, limit),
                )
            )
        return jobs

    @staticmethod
    def _assemble(outcomes: list[AdapterOutcome], limit: int) -> dict[str, Any]:
        used: list[str] = []
        timed_out: list[str] = []
        failed: list[dict[str, str]] = []
        answers: dict[str, str] = {}

        for outcome in outcomes:
            if outcome.timed_out:
                timed_out.append(outcome.name)
                continue
            if not outcome.success:
                failed.append({"name": outcome.name, "error": outcome.error})
                continue
            used.append(outcome.name)
            answer = str(outcome.extra.get("answer") or "").strip()
            if answer:
                answers[outcome.name] = answer

        rows = merge_rows(outcomes, limit)
        fathom_meta: dict[str, Any] = {
            "used": used,
            "timed_out": timed_out,
            "failed": failed,
        }
        if answers:
            fathom_meta["answers"] = answers

        if not used:
            parts = []
            for name in timed_out:
                parts.append(f"{name} timed out")
            for item in failed:
                parts.append(f"{item['name']}: {item['error']}")
            detail = "; ".join(parts) if parts else "no adapters ran"
            return {
                "success": False,
                "error": f"Fathom had no usable adapters ({detail})",
                "data": {
                    "web": [],
                    "provider": "fathom",
                    "provider_label": PROVIDER_LABEL,
                    "fathom": fathom_meta,
                },
            }

        return {
            "success": True,
            "data": {
                "web": rows,
                "provider": "fathom",
                "provider_label": PROVIDER_LABEL,
                "fathom": fathom_meta,
            },
        }

    def extract(self, urls: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        return self._exa.extract(list(urls))
