"""ChatGPT adapter — chatgpt2api POST /v1/search."""

from __future__ import annotations

import logging
from typing import Any

from agent.web_search_provider import get_provider_env

from plugins.web.fathom.common import (
    AdapterOutcome,
    configured_base_url,
    configured_secret,
    configured_text,
    load_config_section,
    nested_section,
    resolve_timeout,
    shared_timeout,
    timeout_outcome,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://wcpa.edmundvps.site:3000/v1"
DEFAULT_MODEL = "gpt-5-6-thinking"
DEFAULT_EFFORT = "extended"
_VALID_EFFORT = {"standard", "max", "extended"}


def rows_from_chatgpt(data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    sources = data.get("sources")
    if not isinstance(sources, list):
        sources = []
    rows: list[dict[str, Any]] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        rows.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": url,
                "description": str(
                    item.get("snippet") or item.get("description") or ""
                ).strip(),
                "position": len(rows) + 1,
            }
        )
        if len(rows) >= limit:
            break
    return rows


class ChatGPTAdapter:
    name = "chatgpt"

    def _section(self) -> dict[str, Any]:
        return nested_section(load_config_section(("web", "fathom")), "chatgpt")

    def inputs(self) -> dict[str, str]:
        chatgpt = self._section()
        return {
            "api_key": configured_secret("CHATGPT_SEARCH_API_KEY", chatgpt),
            "base_url": configured_base_url(
                get_provider_env("CHATGPT_SEARCH_BASE_URL"),
                chatgpt.get("base_url"),
            ),
            "model": configured_text(
                get_provider_env("CHATGPT_SEARCH_MODEL"),
                chatgpt.get("model"),
            ),
            "effort": configured_text(
                get_provider_env("CHATGPT_SEARCH_EFFORT"),
                chatgpt.get("effort"),
            ).lower(),
        }

    def enabled(self) -> bool:
        return all(self.inputs().values())

    def is_available(self) -> bool:
        return self.enabled()

    def timeout(self) -> float:
        return float(self.load_settings()["timeout"])

    def api_key(self) -> str:
        return self.inputs()["api_key"]

    def load_settings(self) -> dict[str, Any]:
        fathom = load_config_section(("web", "fathom"))
        chatgpt = nested_section(fathom, "chatgpt")
        raw = self.inputs()
        effort = raw["effort"]
        if effort and effort not in _VALID_EFFORT:
            raise ValueError(
                f"Invalid web.fathom.chatgpt.effort {effort!r}. "
                f"Use one of: {sorted(_VALID_EFFORT)}"
            )
        timeout = resolve_timeout(
            get_provider_env("CHATGPT_SEARCH_TIMEOUT"),
            chatgpt.get("timeout"),
            default=shared_timeout(fathom),
        )
        return {
            "base_url": raw["base_url"],
            "model": raw["model"],
            "timeout": timeout,
            "effort": effort,
            "api_key": raw["api_key"],
        }

    def search(self, query: str, limit: int) -> AdapterOutcome:
        if not self.enabled():
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="ChatGPT skipped because an input is empty.",
            )
        try:
            settings = self.load_settings()
        except ValueError as exc:
            return AdapterOutcome(name=self.name, success=False, error=str(exc))

        api_key = settings["api_key"]
        timeout = float(settings["timeout"])
        effort = settings["effort"]
        payload = {
            "prompt": query,
            "model": settings["model"],
            "reasoning_effort": effort,
            "thinking_effort": effort,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            import httpx
        except ImportError:
            return AdapterOutcome(name=self.name, success=False, error="httpx is not installed")

        logger.info(
            "Fathom chatgpt via %s model=%s effort=%s timeout=%.0fs query=%r",
            settings["base_url"],
            settings["model"],
            effort,
            timeout,
            query,
        )

        try:
            resp = httpx.post(
                f"{settings['base_url']}/search",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning("Fathom chatgpt timed out after %.0fs: %s", timeout, exc)
            return timeout_outcome(self.name, timeout, exc)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = ""
            try:
                body = exc.response.text[:400] if exc.response is not None else ""
            except Exception:
                body = ""
            logger.warning("Fathom chatgpt HTTP %d: %s", status, body)
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=f"ChatGPT search returned HTTP {status}: {body}".rstrip(),
            )
        except httpx.RequestError as exc:
            logger.warning("Fathom chatgpt request error: %s", exc)
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=f"Could not reach ChatGPT search: {exc}",
            )

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Fathom chatgpt bad JSON: %s", exc)
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="Could not parse ChatGPT search reply as JSON",
            )

        if not isinstance(data, dict):
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="ChatGPT search reply was not a JSON object",
            )

        api_error = data.get("error")
        if isinstance(api_error, dict):
            err_msg = api_error.get("message") or api_error.get("code") or "unknown error"
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=f"ChatGPT search returned an error: {err_msg}",
            )
        if isinstance(api_error, str) and api_error.strip():
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=f"ChatGPT search returned an error: {api_error.strip()}",
            )

        rows = rows_from_chatgpt(data, limit)
        answer = str(data.get("answer") or "").strip()
        extra: dict[str, Any] = {}
        if answer:
            extra["answer"] = answer
        return AdapterOutcome(name=self.name, success=True, rows=rows, extra=extra)
