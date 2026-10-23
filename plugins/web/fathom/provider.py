"""Fathom — multi-provider web search.

Live adapters: ChatGPT (chatgpt2api ``/v1/search``),
Exa (``POST /search`` plus ``POST /contents``),
and Tavily (``POST /search`` plus ``POST /extract``).

Each adapter has its own timeout (default 120s). A timed-out adapter is
dropped for that call; remaining adapters still contribute. An adapter with
any empty input is skipped. Code defaults are not filled in.

Config::

    web:
      search_backend: "fathom"
      fathom:
        timeout: 120
        chatgpt:
          base_url: "http://wcpa.edmundvps.site:3000/v1"
          model: "gpt-5-6-thinking"
          effort: "extended"
          key_env: "CHATGPT_SEARCH_API_KEY"
        exa:
          base_url: "http://wcpap.edmundvps.site:19881"
          key_env: "EXA_SEARCH_API_KEY"
          search_defaults:
            type: deep-reasoning
            numResults: 10
            contents:
              highlights: true
          extract_defaults:
            text: true
            highlights: true
        tavily:
          base_url: "http://wcpap.edmundvps.site:19882"
          key_env: "TAVILY_SEARCH_API_KEY"
          search_defaults:
            search_depth: advanced
            max_results: 10
            include_answer: true
          extract_defaults:
            extract_depth: advanced
            format: markdown

Env overrides (Desktop Tools panel can write these):

    CHATGPT_SEARCH_API_KEY
    CHATGPT_SEARCH_BASE_URL
    CHATGPT_SEARCH_MODEL
    CHATGPT_SEARCH_EFFORT
    CHATGPT_SEARCH_TIMEOUT
    EXA_SEARCH_API_KEY
    EXA_SEARCH_BASE_URL
    EXA_SEARCH_DEFAULTS
    EXA_EXTRACT_DEFAULTS
    EXA_SEARCH_TIMEOUT
    TAVILY_SEARCH_API_KEY
    TAVILY_SEARCH_BASE_URL
    TAVILY_SEARCH_DEFAULTS
    TAVILY_EXTRACT_DEFAULTS
    TAVILY_SEARCH_TIMEOUT
    FATHOM_TIMEOUT
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
from plugins.web.fathom.tavily import (
    DEFAULT_API_KEY as TAVILY_DEFAULT_API_KEY,
    DEFAULT_BASE_URL as TAVILY_DEFAULT_BASE_URL,
    DEFAULT_EXTRACT_DEFAULTS as TAVILY_EXTRACT_DEFAULTS,
    DEFAULT_SEARCH_DEFAULTS as TAVILY_SEARCH_DEFAULTS,
    TavilyAdapter,
)

logger = logging.getLogger(__name__)


class FathomWebSearchProvider(WebSearchProvider):
    """Ensemble search backend. ChatGPT, Exa, and Tavily run in parallel."""

    def __init__(self) -> None:
        self._chatgpt = ChatGPTAdapter()
        self._exa = ExaAdapter()
        self._tavily = TavilyAdapter()

    def _adapters(self):
        return (self._chatgpt, self._exa, self._tavily)

    @property
    def name(self) -> str:
        return "fathom"

    @property
    def display_name(self) -> str:
        return "Fathom"

    def is_available(self) -> bool:
        return any(adapter.is_available() for adapter in self._adapters())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            "name": "Fathom",
            "badge": "ensemble",
            "tag": (
                "Multi-provider web search. ChatGPT, Exa, and Tavily run in parallel; "
                "a 120s timeout drops that adapter for the call. "
                "An empty input skips that provider. "
                "Exa and Tavily also extract page content."
            ),
            "env_vars": [
                {
                    "key": "CHATGPT_SEARCH_API_KEY",
                    "prompt": "ChatGPT search API key",
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
                {
                    "key": "CHATGPT_SEARCH_EFFORT",
                    "prompt": (
                        "ChatGPT reasoning_effort and thinking_effort: "
                        "standard|max|extended"
                    ),
                    "default": CHATGPT_DEFAULT_EFFORT,
                },
                {
                    "key": "EXA_SEARCH_API_KEY",
                    "prompt": "Exa API key",
                    "default": EXA_DEFAULT_API_KEY,
                },
                {
                    "key": "EXA_SEARCH_BASE_URL",
                    "prompt": "Exa base URL. Search is POST /search; extract is POST /contents.",
                    "default": EXA_DEFAULT_BASE_URL,
                },
                {
                    "key": "EXA_SEARCH_DEFAULTS",
                    "prompt": (
                        "Exa POST /search JSON defaults. query is set per call. "
                        "numResults is the Exa request size. Fathom raises it to the "
                        "candidate pool when the configured value is smaller. "
                        "The tool limit still caps the final rows."
                    ),
                    "default": DEFAULT_SEARCH_DEFAULTS,
                },
                {
                    "key": "EXA_EXTRACT_DEFAULTS",
                    "prompt": "Exa POST /contents JSON defaults. urls is set per call.",
                    "default": DEFAULT_EXTRACT_DEFAULTS,
                },
                {
                    "key": "TAVILY_SEARCH_API_KEY",
                    "prompt": "Tavily API key",
                    "default": TAVILY_DEFAULT_API_KEY,
                },
                {
                    "key": "TAVILY_SEARCH_BASE_URL",
                    "prompt": "Tavily base URL. Search is POST /search; extract is POST /extract.",
                    "default": TAVILY_DEFAULT_BASE_URL,
                },
                {
                    "key": "TAVILY_SEARCH_DEFAULTS",
                    "prompt": (
                        "Tavily POST /search JSON defaults. query is set per call. "
                        "max_results is the Tavily request size. Fathom raises it to "
                        "the candidate pool when the configured value is smaller "
                        "(Tavily's own cap is 20). The tool limit still caps the final rows."
                    ),
                    "default": TAVILY_SEARCH_DEFAULTS,
                },
                {
                    "key": "TAVILY_EXTRACT_DEFAULTS",
                    "prompt": "Tavily POST /extract JSON defaults. urls is set per call.",
                    "default": TAVILY_EXTRACT_DEFAULTS,
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
        from plugins.web.fathom.common import candidate_limit

        pool_limit = candidate_limit(limit)
        jobs = self._jobs(query, pool_limit)
        if not jobs:
            return {
                "success": False,
                "error": (
                    "No Fathom providers configured. Fill every ChatGPT, Exa, "
                    "and Tavily input; an empty field skips that provider."
                ),
            }

        logger.info(
            "Fathom ensemble query=%r limit=%d pool=%d adapters=%s",
            query,
            limit,
            pool_limit,
            [name for name, _timeout, _call in jobs],
        )
        outcomes = dispatch_adapters(jobs)
        baseline = self._assemble(outcomes, limit)
        if not baseline.get("success"):
            return baseline
        from plugins.web.fathom.judge import adjudicate

        judged = adjudicate(self, query, outcomes, limit)
        if judged.response is None and judged.error == "interrupted":
            return {"success": False, "error": "Interrupted"}
        if judged.response is None:
            baseline["data"]["fathom"]["judge"] = {
                "fallback": "merge",
                "error": judged.error,
            }
            logger.info(
                "Fathom judge fallback=merge query=%r error=%s",
                query,
                judged.error,
            )
            return baseline
        return judged.response

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

        for outcome in outcomes:
            if outcome.timed_out:
                timed_out.append(outcome.name)
                continue
            if not outcome.success:
                failed.append({"name": outcome.name, "error": outcome.error})
                continue
            used.append(outcome.name)

        rows = merge_rows(outcomes, limit)
        fathom_meta: dict[str, Any] = {
            "used": used,
            "timed_out": timed_out,
            "failed": failed,
        }

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
                    "fathom": fathom_meta,
                },
            }

        return {
            "success": True,
            "data": {
                "web": rows,
                "provider": "fathom",
                "fathom": fathom_meta,
            },
        }

    def extract(self, urls: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        urls = list(urls)
        if not urls:
            return []
        adapters = [adapter for adapter in (self._exa, self._tavily) if adapter.enabled()]
        if not adapters:
            from plugins.web._common import extract_fail

            return extract_fail(
                urls,
                "No Fathom extract provider configured. Fill every Exa and Tavily input.",
            )
        from plugins.web._common import document, page_error

        batches = [(adapter.name, adapter.extract(urls)) for adapter in adapters]
        packed: list[dict[str, Any]] = []
        for index, url in enumerate(urls):
            parts: list[str] = []
            title = ""
            any_content = False
            errors: list[str] = []
            for name, batch in batches:
                page = batch[index] if index < len(batch) else None
                if not isinstance(page, dict):
                    errors.append(f"{name}: no result")
                    parts.append(f"[{name}]\nerror: no result")
                    continue
                page_title = str(page.get("title") or "").strip()
                if page_title and not title:
                    title = page_title
                if page.get("error"):
                    errors.append(f"{name}: {page['error']}")
                    parts.append(f"[{name}]\nerror: {page['error']}")
                    continue
                body = str(page.get("content") or "").strip()
                if page_title:
                    parts.append(f"[{name}]\ntitle: {page_title}\n\n{body}")
                else:
                    parts.append(f"[{name}]\n\n{body}")
                if body:
                    any_content = True
            if not any_content:
                packed.append(page_error(url, "; ".join(errors) if errors else "No extract result"))
                continue
            packed.append(document(url, title, "\n\n".join(parts)))
        return packed
