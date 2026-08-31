"""Fathom — multi-provider web search.

Live adapters: Grok (Responses API) and ChatGPT (chatgpt2api ``/v1/search``).
Exa and Tavily land next.

Each adapter has its own timeout (default 90s). A timed-out adapter is
dropped for that call; remaining adapters still contribute.

Config::

    web:
      search_backend: "fathom"
      fathom:
        timeout: 90
        base_url: "http://wcpa.edmundvps.site:18453/v1"
        model: "grok-4.20-multi-agent-0309"
        effort: "high"
        enable_web_search: true
        enable_x_search: true
        key_env: "GROK2API_API_KEY"
        chatgpt:
          base_url: "http://wcpa.edmundvps.site:3000/v1"
          model: "gpt-5-6-thinking"
          timeout: 90
          key_env: "CHATGPT2API_API_KEY"

Env overrides (Desktop Tools panel can write these):

    GROK_SEARCH_API_KEY
    GROK_SEARCH_BASE_URL
    GROK_SEARCH_MODEL
    GROK_SEARCH_EFFORT
    GROK_SEARCH_TIMEOUT
    CHATGPT_SEARCH_API_KEY
    CHATGPT_SEARCH_BASE_URL
    CHATGPT_SEARCH_MODEL
    CHATGPT_SEARCH_TIMEOUT
    FATHOM_TIMEOUT

If adapter base_url / API key are unset, Fathom reuses
``providers.grok2api`` and ``providers.chatgpt2api``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider

from plugins.web.fathom.chatgpt import ChatGPTAdapter, DEFAULT_BASE_URL as CHATGPT_DEFAULT_BASE_URL
from plugins.web.fathom.chatgpt import DEFAULT_MODEL as CHATGPT_DEFAULT_MODEL
from plugins.web.fathom.common import (
    AdapterOutcome,
    DEFAULT_PROVIDER_TIMEOUT,
    PROVIDER_LABEL,
    dispatch_adapters,
    merge_rows,
)
from plugins.web.fathom.grok import DEFAULT_BASE_URL as GROK_DEFAULT_BASE_URL
from plugins.web.fathom.grok import DEFAULT_EFFORT, DEFAULT_MODEL as GROK_DEFAULT_MODEL
from plugins.web.fathom.grok import GrokAdapter

logger = logging.getLogger(__name__)


class FathomWebSearchProvider(WebSearchProvider):
    """Ensemble search backend. Grok and ChatGPT run in parallel."""

    def __init__(self) -> None:
        self._grok = GrokAdapter()
        self._chatgpt = ChatGPTAdapter()

    @property
    def name(self) -> str:
        return "fathom"

    @property
    def display_name(self) -> str:
        return PROVIDER_LABEL

    def is_available(self) -> bool:
        return self._grok.is_available() or self._chatgpt.is_available()

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": PROVIDER_LABEL,
            "badge": "ensemble",
            "tag": (
                "Multi-provider web search. Grok and ChatGPT run in parallel; "
                "a 90s timeout drops that adapter for the call. "
                "Exa and Tavily come next."
            ),
            "env_vars": [
                {
                    "key": "GROK_SEARCH_API_KEY",
                    "prompt": "Grok API key. Unset uses GROK2API_API_KEY.",
                    "fallback_key": "GROK2API_API_KEY",
                },
                {
                    "key": "GROK_SEARCH_BASE_URL",
                    "prompt": "Grok Responses API base URL",
                    "default": GROK_DEFAULT_BASE_URL,
                },
                {
                    "key": "GROK_SEARCH_MODEL",
                    "prompt": "Grok model id",
                    "default": GROK_DEFAULT_MODEL,
                },
                {
                    "key": "GROK_SEARCH_EFFORT",
                    "prompt": "Grok reasoning.effort: low|medium|high|xhigh (high = 16 agents)",
                    "default": DEFAULT_EFFORT,
                },
                {
                    "key": "CHATGPT_SEARCH_API_KEY",
                    "prompt": "ChatGPT search API key. Unset uses CHATGPT2API_API_KEY.",
                    "fallback_key": "CHATGPT2API_API_KEY",
                },
                {
                    "key": "CHATGPT_SEARCH_BASE_URL",
                    "prompt": "ChatGPT /v1/search base URL",
                    "default": CHATGPT_DEFAULT_BASE_URL,
                },
                {
                    "key": "CHATGPT_SEARCH_MODEL",
                    "prompt": "ChatGPT search model",
                    "default": CHATGPT_DEFAULT_MODEL,
                },
            ],
        }

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
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
            return {
                "success": False,
                "error": (
                    "No Fathom credentials. Set GROK_SEARCH_API_KEY / "
                    "GROK2API_API_KEY or CHATGPT_SEARCH_API_KEY / "
                    "CHATGPT2API_API_KEY."
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
        for adapter in (self._grok, self._chatgpt):
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
    def _assemble(outcomes: List[AdapterOutcome], limit: int) -> Dict[str, Any]:
        used: List[str] = []
        timed_out: List[str] = []
        failed: List[Dict[str, str]] = []
        answers: Dict[str, str] = {}

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
        fathom_meta: Dict[str, Any] = {
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
