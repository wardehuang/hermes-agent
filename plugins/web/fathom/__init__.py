"""Fathom web search plugin — bundled, auto-loaded."""

from __future__ import annotations

from plugins.web.fathom.provider import FathomWebSearchProvider


def register(ctx) -> None:
    ctx.register_web_search_provider(FathomWebSearchProvider())
