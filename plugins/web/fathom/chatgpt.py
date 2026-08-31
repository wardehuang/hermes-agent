"""ChatGPT adapter — chatgpt2api POST /v1/search."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.web_search_provider import get_provider_env

from plugins.web.fathom.common import (
    AdapterOutcome,
    load_config_section,
    nested_section,
    normalize_base_url,
    resolve_timeout,
    shared_timeout,
    timeout_outcome,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://wcpa.edmundvps.site:3000/v1"
DEFAULT_MODEL = "gpt-5-6-thinking"


def rows_from_chatgpt(data: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    sources = data.get("sources")
    if not isinstance(sources, list):
        sources = []
    rows: List[Dict[str, Any]] = []
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

    def is_available(self) -> bool:
        return bool(self.api_key())

    def timeout(self) -> float:
        return float(self.load_settings()["timeout"])

    def api_key(self) -> str:
        direct = get_provider_env("CHATGPT_SEARCH_API_KEY")
        if direct:
            return direct
        fathom = load_config_section(("web", "fathom"))
        chatgpt = nested_section(fathom, "chatgpt")
        key_env = str(chatgpt.get("key_env") or "").strip()
        if key_env:
            value = get_provider_env(key_env)
            if value:
                return value
        chatgpt2api = get_provider_env("CHATGPT2API_API_KEY")
        if chatgpt2api:
            return chatgpt2api
        provider = load_config_section(("providers", "chatgpt2api"))
        provider_key_env = str(provider.get("key_env") or "").strip()
        if provider_key_env:
            return get_provider_env(provider_key_env)
        return ""

    def load_settings(self) -> Dict[str, Any]:
        fathom = load_config_section(("web", "fathom"))
        chatgpt = nested_section(fathom, "chatgpt")
        chatgpt2api = load_config_section(("providers", "chatgpt2api"))
        chatgpt2api_url = str(
            chatgpt2api.get("api") or chatgpt2api.get("base_url") or ""
        ).strip()

        base_url = normalize_base_url(
            get_provider_env("CHATGPT_SEARCH_BASE_URL")
            or str(chatgpt.get("base_url") or chatgpt2api_url or DEFAULT_BASE_URL),
            DEFAULT_BASE_URL,
        )
        model = (
            get_provider_env("CHATGPT_SEARCH_MODEL")
            or str(chatgpt.get("model") or DEFAULT_MODEL)
        ).strip() or DEFAULT_MODEL
        timeout = resolve_timeout(
            get_provider_env("CHATGPT_SEARCH_TIMEOUT"),
            chatgpt.get("timeout"),
            default=shared_timeout(fathom),
        )
        return {
            "base_url": base_url,
            "model": model,
            "timeout": timeout,
        }

    def search(self, query: str, limit: int) -> AdapterOutcome:
        api_key = self.api_key()
        if not api_key:
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=(
                    "No ChatGPT credentials. Set CHATGPT_SEARCH_API_KEY "
                    "or CHATGPT2API_API_KEY."
                ),
            )

        try:
            settings = self.load_settings()
        except ValueError as exc:
            return AdapterOutcome(name=self.name, success=False, error=str(exc))

        timeout = float(settings["timeout"])
        payload = {"prompt": query, "model": settings["model"]}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            import httpx
        except ImportError:
            return AdapterOutcome(name=self.name, success=False, error="httpx is not installed")

        logger.info(
            "Fathom chatgpt via %s model=%s timeout=%.0fs query=%r",
            settings["base_url"],
            settings["model"],
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
        extra: Dict[str, Any] = {}
        if answer:
            extra["answer"] = answer
        return AdapterOutcome(name=self.name, success=True, rows=rows, extra=extra)
