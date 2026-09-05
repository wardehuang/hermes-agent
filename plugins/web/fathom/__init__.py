"""Fathom web search plugin — bundled, auto-loaded."""

from __future__ import annotations

from typing import Any, Mapping

from plugins.web.fathom.provider import FathomWebSearchProvider

SEARCH_DISPATCH_SECTION_ID = "web-fathom.search-dispatch"
SEARCH_DISPATCH_PROMPT = (
    "Call the search function listed in the tools array by that exact name "
    "(web_search or cpa_client_web_search). Both execute Hermes web_search / "
    "Fathom. Do not wrap a search in execute_code or hermes_tools.web_search; "
    "Desktop then records execute_code and hides the Fathom badge."
)


def search_dispatch_section(_session_info: Mapping[str, Any]) -> str:
    from agent.web_search_registry import get_active_search_provider

    provider = get_active_search_provider()
    if provider is None or provider.name != "fathom":
        return ""
    return SEARCH_DISPATCH_PROMPT


def register(ctx) -> None:
    ctx.register_web_search_provider(FathomWebSearchProvider())
    ctx.register_system_prompt_section(
        SEARCH_DISPATCH_SECTION_ID,
        search_dispatch_section,
        position="after_memory",
        max_chars=800,
    )
