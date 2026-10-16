"""Tavily adapter — FreeAPI gateway POST /search and POST /extract."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from agent.web_search_provider import current_search_topic, get_provider_env

from plugins.web._common import document, extract_fail, page_error
from plugins.web.fathom.common import (
    AdapterOutcome,
    load_config_section,
    nested_section,
    normalize_base_url,
    resolve_flag,
    resolve_timeout,
    shared_timeout,
    timeout_outcome,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://wcpap.edmundvps.site:19882"
DEFAULT_API_KEY = "sk-Q0Moji4ag5Fell2STBTvzUd4XBicntqzTeNtkoiI"
DEFAULT_SEARCH_BODY: dict[str, Any] = {
    "search_depth": "advanced",
    "max_results": 10,
    "include_answer": True,
}
DEFAULT_EXTRACT_BODY: dict[str, Any] = {
    "extract_depth": "advanced",
    "format": "markdown",
}
DEFAULT_SEARCH_DEFAULTS = json.dumps(DEFAULT_SEARCH_BODY, separators=(",", ":"))
DEFAULT_EXTRACT_DEFAULTS = json.dumps(DEFAULT_EXTRACT_BODY, separators=(",", ":"))
_VALID_SEARCH_DEPTHS = {"basic", "fast", "ultra-fast", "advanced"}
_VALID_TOPICS = {"general", "news", "finance"}
_VALID_EXTRACT_DEPTHS = {"basic", "advanced"}
_VALID_FORMATS = {"markdown", "text"}
_MAX_EXTRACT_URLS = 20


def _parse_object(raw: Any, label: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        value = copy.deepcopy(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError(f"{label} is empty")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    else:
        raise ValueError(f"{label} must be a JSON object")
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _configured_object(
    env_name: str,
    yaml_value: Any,
    default: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    raw = get_provider_env(env_name)
    if raw:
        return _parse_object(raw, label)
    if yaml_value is None or yaml_value == "":
        return copy.deepcopy(default)
    return _parse_object(yaml_value, label)


def _validate_topic(topic: Any) -> None:
    if not isinstance(topic, str) or topic not in _VALID_TOPICS:
        raise ValueError(
            f"Invalid Tavily topic {topic!r}. Use one of: {sorted(_VALID_TOPICS)}"
        )


def _validate_search_body(body: dict[str, Any]) -> None:
    depth = body.get("search_depth")
    if depth is not None and (not isinstance(depth, str) or depth not in _VALID_SEARCH_DEPTHS):
        raise ValueError(
            f"Invalid Tavily search_depth {depth!r}. "
            f"Use one of: {sorted(_VALID_SEARCH_DEPTHS)}"
        )
    count = body.get("max_results")
    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 20
    ):
        raise ValueError("Tavily max_results must be an integer from 0 to 20")
    include_answer = body.get("include_answer")
    if include_answer is not None and not isinstance(include_answer, bool) and include_answer != "advanced":
        raise ValueError('Tavily include_answer must be a boolean or "advanced"')
    if "topic" in body:
        _validate_topic(body.get("topic"))


def _validate_extract_body(body: dict[str, Any]) -> None:
    depth = body.get("extract_depth")
    if depth is not None and (not isinstance(depth, str) or depth not in _VALID_EXTRACT_DEPTHS):
        raise ValueError(
            f"Invalid Tavily extract_depth {depth!r}. "
            f"Use one of: {sorted(_VALID_EXTRACT_DEPTHS)}"
        )
    fmt = body.get("format")
    if fmt is not None and (not isinstance(fmt, str) or fmt not in _VALID_FORMATS):
        raise ValueError(
            f"Invalid Tavily format {fmt!r}. Use one of: {sorted(_VALID_FORMATS)}"
        )


def rows_from_tavily(data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results = data.get("results")
    if not isinstance(results, list):
        return []
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = 5
    cap = max(1, min(cap, 100))
    rows: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        description = str(item.get("content") or item.get("snippet") or "").strip()
        rows.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": url,
                "description": description,
                "position": len(rows) + 1,
            }
        )
        if len(rows) >= cap:
            break
    return rows


def _index_by_url(items: Any) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        return indexed
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url.strip():
            indexed.setdefault(url.strip(), item)
    return indexed


def _extract_text(item: dict[str, Any]) -> str:
    raw = item.get("raw_content")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    content = item.get("content")
    if isinstance(content, str):
        return content.strip()
    return ""


def _failed_message(item: dict[str, Any]) -> str:
    err = item.get("error")
    if isinstance(err, str) and err.strip():
        return err.strip()
    if isinstance(err, dict):
        message = err.get("message") or err.get("tag") or err.get("code")
        if message:
            return str(message)
    return "Tavily extract failed"


class TavilyAdapter:
    name = "tavily"

    def enabled(self) -> bool:
        fathom = load_config_section(("web", "fathom"))
        tavily = nested_section(fathom, "tavily")
        yaml_value = tavily.get("enabled") if "enabled" in tavily else None
        return resolve_flag("TAVILY_SEARCH_ENABLED", yaml_value, True)

    def is_available(self) -> bool:
        return self.enabled() and bool(self.api_key())

    def timeout(self) -> float:
        return float(self.load_settings()["timeout"])

    def api_key(self) -> str:
        direct = get_provider_env("TAVILY_SEARCH_API_KEY")
        if direct:
            return direct
        tavily = nested_section(load_config_section(("web", "fathom")), "tavily")
        key_env = str(tavily.get("key_env") or "").strip()
        if key_env:
            value = get_provider_env(key_env)
            if value:
                return value
        return DEFAULT_API_KEY

    def load_settings(self) -> dict[str, Any]:
        fathom = load_config_section(("web", "fathom"))
        tavily = nested_section(fathom, "tavily")
        base_url = normalize_base_url(
            get_provider_env("TAVILY_SEARCH_BASE_URL")
            or str(tavily.get("base_url") or DEFAULT_BASE_URL),
            DEFAULT_BASE_URL,
        )
        timeout = resolve_timeout(
            get_provider_env("TAVILY_SEARCH_TIMEOUT"),
            tavily.get("timeout"),
            default=shared_timeout(fathom),
        )
        return {"base_url": base_url, "timeout": timeout}

    def search_body(self) -> dict[str, Any]:
        tavily = nested_section(load_config_section(("web", "fathom")), "tavily")
        body = _configured_object(
            "TAVILY_SEARCH_DEFAULTS",
            tavily.get("search_defaults"),
            DEFAULT_SEARCH_BODY,
            "Tavily search defaults",
        )
        _validate_search_body(body)
        return body

    def extract_body(self) -> dict[str, Any]:
        tavily = nested_section(load_config_section(("web", "fathom")), "tavily")
        body = _configured_object(
            "TAVILY_EXTRACT_DEFAULTS",
            tavily.get("extract_defaults"),
            DEFAULT_EXTRACT_BODY,
            "Tavily extract defaults",
        )
        _validate_extract_body(body)
        return body

    def _post(self, path: str, payload: dict[str, Any], kind: str) -> dict[str, Any]:
        api_key = self.api_key()
        if not api_key:
            raise ValueError("No Tavily credentials. Set TAVILY_SEARCH_API_KEY.")
        settings = self.load_settings()
        timeout = float(settings["timeout"])
        url = f"{settings['base_url']}{path}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            import httpx
        except ImportError as exc:
            raise ValueError("httpx is not installed") from exc

        logger.info("Fathom tavily %s via %s timeout=%.0fs", kind, url, timeout)
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = exc.response.text[:400] if exc.response is not None else ""
            raise ValueError(f"Tavily {kind} returned HTTP {status}: {body}".rstrip()) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"Could not reach Tavily {kind}: {exc}") from exc

        try:
            data = resp.json()
        except Exception as exc:
            raise ValueError(f"Could not parse Tavily {kind} reply as JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Tavily {kind} reply was not a JSON object")
        api_error = data.get("error")
        if isinstance(api_error, dict):
            err_msg = api_error.get("message") or api_error.get("code") or "unknown error"
            raise ValueError(f"Tavily {kind} returned an error: {err_msg}")
        if isinstance(api_error, str) and api_error.strip():
            raise ValueError(f"Tavily {kind} returned an error: {api_error.strip()}")
        return data

    def search(self, query: str, limit: int) -> AdapterOutcome:
        if not self.enabled():
            return AdapterOutcome(name=self.name, success=False, error="Tavily is disabled")
        try:
            payload = self.search_body()
            settings = self.load_settings()
            topic = current_search_topic()
            if topic:
                _validate_topic(topic)
                payload["topic"] = topic
        except ValueError as exc:
            return AdapterOutcome(name=self.name, success=False, error=str(exc))
        payload["query"] = query
        timeout = float(settings["timeout"])
        try:
            data = self._post("/search", payload, "search")
        except TimeoutError as exc:
            logger.warning("Fathom tavily search timed out after %.0fs: %s", timeout, exc)
            return timeout_outcome(self.name, timeout, exc)
        except ValueError as exc:
            logger.warning("Fathom tavily search failed: %s", exc)
            return AdapterOutcome(name=self.name, success=False, error=str(exc))
        results = data.get("results")
        if results is not None and not isinstance(results, list):
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="Tavily search results was not an array",
            )
        answer = str(data.get("answer") or "").strip()
        extra = {"answer": answer} if answer else {}
        return AdapterOutcome(
            name=self.name,
            success=True,
            rows=rows_from_tavily(data, limit),
            extra=extra,
        )

    def extract(self, urls: list[str]) -> list[dict[str, Any]]:
        if not urls:
            return []
        if not self.enabled():
            return extract_fail(urls, "Tavily is disabled. Turn on TAVILY_SEARCH_ENABLED.")
        if len(urls) > _MAX_EXTRACT_URLS:
            return extract_fail(urls, "Tavily extract accepts 1 to 20 URLs")
        try:
            payload = self.extract_body()
            settings = self.load_settings()
        except ValueError as exc:
            return extract_fail(urls, str(exc))
        payload["urls"] = list(urls)
        timeout = float(settings["timeout"])
        try:
            data = self._post("/extract", payload, "extract")
        except TimeoutError as exc:
            logger.warning("Fathom tavily extract timed out after %.0fs: %s", timeout, exc)
            return extract_fail(urls, f"tavily timed out after {timeout:g}s: {exc}")
        except ValueError as exc:
            logger.warning("Fathom tavily extract failed: %s", exc)
            return extract_fail(urls, str(exc))

        results = data.get("results")
        failed = data.get("failed_results")
        if results is not None and not isinstance(results, list):
            return extract_fail(urls, "Tavily extract results was not an array")
        if failed is not None and not isinstance(failed, list):
            return extract_fail(urls, "Tavily extract failed_results was not an array")
        by_result = _index_by_url(results)
        by_failed = _index_by_url(failed)
        pages: list[dict[str, Any]] = []
        for url in urls:
            item = by_result.get(url)
            if item is not None:
                title = str(item.get("title") or "").strip()
                pages.append(document(url, title, _extract_text(item)))
                continue
            failure = by_failed.get(url)
            if failure is not None:
                pages.append(page_error(url, _failed_message(failure)))
                continue
            pages.append(page_error(url, "Tavily extract returned no result for this URL"))
        return pages
