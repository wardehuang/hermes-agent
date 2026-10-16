"""Exa adapter — FreeAPI gateway POST /search and POST /contents."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from agent.web_search_provider import get_provider_env

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

DEFAULT_BASE_URL = "http://wcpap.edmundvps.site:19881"
DEFAULT_API_KEY = "sk-Q0Moji4ag5Fell2STBTvzUd4XBicntqzTeNtkoiI"
DEFAULT_SEARCH_BODY: dict[str, Any] = {
    "type": "deep-reasoning",
    "numResults": 10,
    "contents": {"highlights": True},
}
DEFAULT_EXTRACT_BODY: dict[str, Any] = {"text": True, "highlights": True}
DEFAULT_SEARCH_DEFAULTS = json.dumps(DEFAULT_SEARCH_BODY, separators=(",", ":"))
DEFAULT_EXTRACT_DEFAULTS = json.dumps(DEFAULT_EXTRACT_BODY, separators=(",", ":"))
_VALID_SEARCH_TYPES = {
    "instant",
    "fast",
    "auto",
    "deep-lite",
    "deep",
    "deep-reasoning",
}


def _compact_error(status: dict[str, Any]) -> str:
    err = status.get("error")
    if isinstance(err, str) and err.strip():
        return err.strip()
    if isinstance(err, dict):
        tag = err.get("tag") or err.get("message") or err.get("code")
        code = err.get("httpStatusCode")
        if tag and code:
            return f"{tag} ({code})"
        if tag:
            return str(tag)
    state = str(status.get("status") or "error").strip() or "error"
    return f"Exa contents status: {state}"


def _description(item: dict[str, Any]) -> str:
    highlights = item.get("highlights")
    if isinstance(highlights, list):
        parts = [str(part).strip() for part in highlights if str(part).strip()]
        if parts:
            return " ".join(parts)
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    summary = item.get("summary")
    if isinstance(summary, str):
        return summary.strip()
    return ""


def rows_from_exa(data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
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
        rows.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": url,
                "description": _description(item),
                "position": len(rows) + 1,
            }
        )
        if len(rows) >= cap:
            break
    return rows


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


def _validate_search_body(body: dict[str, Any]) -> None:
    search_type = body.get("type")
    if search_type is not None:
        if not isinstance(search_type, str) or search_type not in _VALID_SEARCH_TYPES:
            raise ValueError(
                f"Invalid Exa search type {search_type!r}. "
                f"Use one of: {sorted(_VALID_SEARCH_TYPES)}"
            )
    count = body.get("numResults")
    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100
    ):
        raise ValueError("Exa search numResults must be an integer from 1 to 100")
    contents = body.get("contents")
    if contents is not None and not isinstance(contents, dict):
        raise ValueError("Exa search contents must be a JSON object")


def _validate_extract_body(body: dict[str, Any]) -> None:
    for key in ("text", "highlights"):
        if key in body and not isinstance(body[key], bool):
            raise ValueError(f"Exa extract {key} must be a boolean")


def _extract_content(item: dict[str, Any]) -> str:
    parts: list[str] = []
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        parts.append(text.strip())
    highlights = item.get("highlights")
    if isinstance(highlights, list):
        snippets = [str(part).strip() for part in highlights if str(part).strip()]
        if snippets:
            parts.append("\n".join(snippets))
    return "\n\n".join(parts)


def _index_items(items: Any) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        return indexed
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in (item.get("url"), item.get("id")):
            if isinstance(key, str) and key.strip():
                indexed.setdefault(key.strip(), item)
    return indexed


class ExaAdapter:
    name = "exa"

    def enabled(self) -> bool:
        fathom = load_config_section(("web", "fathom"))
        exa = nested_section(fathom, "exa")
        yaml_value = exa.get("enabled") if "enabled" in exa else None
        return resolve_flag("EXA_SEARCH_ENABLED", yaml_value, True)

    def is_available(self) -> bool:
        return self.enabled() and bool(self.api_key())

    def timeout(self) -> float:
        return float(self.load_settings()["timeout"])

    def api_key(self) -> str:
        direct = get_provider_env("EXA_SEARCH_API_KEY")
        if direct:
            return direct
        exa = nested_section(load_config_section(("web", "fathom")), "exa")
        key_env = str(exa.get("key_env") or "").strip()
        if key_env:
            value = get_provider_env(key_env)
            if value:
                return value
        return DEFAULT_API_KEY

    def load_settings(self) -> dict[str, Any]:
        fathom = load_config_section(("web", "fathom"))
        exa = nested_section(fathom, "exa")
        base_url = normalize_base_url(
            get_provider_env("EXA_SEARCH_BASE_URL")
            or str(exa.get("base_url") or DEFAULT_BASE_URL),
            DEFAULT_BASE_URL,
        )
        timeout = resolve_timeout(
            get_provider_env("EXA_SEARCH_TIMEOUT"),
            exa.get("timeout"),
            default=shared_timeout(fathom),
        )
        return {"base_url": base_url, "timeout": timeout}

    def search_body(self) -> dict[str, Any]:
        exa = nested_section(load_config_section(("web", "fathom")), "exa")
        body = _configured_object(
            "EXA_SEARCH_DEFAULTS",
            exa.get("search_defaults"),
            DEFAULT_SEARCH_BODY,
            "Exa search defaults",
        )
        _validate_search_body(body)
        return body

    def extract_body(self) -> dict[str, Any]:
        exa = nested_section(load_config_section(("web", "fathom")), "exa")
        body = _configured_object(
            "EXA_EXTRACT_DEFAULTS",
            exa.get("extract_defaults"),
            DEFAULT_EXTRACT_BODY,
            "Exa extract defaults",
        )
        _validate_extract_body(body)
        return body

    def _post(self, path: str, payload: dict[str, Any], kind: str) -> dict[str, Any]:
        api_key = self.api_key()
        if not api_key:
            raise ValueError("No Exa credentials. Set EXA_SEARCH_API_KEY.")
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

        logger.info("Fathom exa %s via %s timeout=%.0fs", kind, url, timeout)
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = exc.response.text[:400] if exc.response is not None else ""
            raise ValueError(f"Exa {kind} returned HTTP {status}: {body}".rstrip()) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"Could not reach Exa {kind}: {exc}") from exc

        try:
            data = resp.json()
        except Exception as exc:
            raise ValueError(f"Could not parse Exa {kind} reply as JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Exa {kind} reply was not a JSON object")
        api_error = data.get("error")
        if isinstance(api_error, dict):
            err_msg = api_error.get("message") or api_error.get("code") or "unknown error"
            raise ValueError(f"Exa {kind} returned an error: {err_msg}")
        if isinstance(api_error, str) and api_error.strip():
            raise ValueError(f"Exa {kind} returned an error: {api_error.strip()}")
        return data

    def search(self, query: str, limit: int) -> AdapterOutcome:
        if not self.enabled():
            return AdapterOutcome(name=self.name, success=False, error="Exa is disabled")
        try:
            payload = self.search_body()
            settings = self.load_settings()
        except ValueError as exc:
            return AdapterOutcome(name=self.name, success=False, error=str(exc))
        payload["query"] = query
        timeout = float(settings["timeout"])
        try:
            data = self._post("/search", payload, "search")
        except TimeoutError as exc:
            logger.warning("Fathom exa search timed out after %.0fs: %s", timeout, exc)
            return timeout_outcome(self.name, timeout, exc)
        except ValueError as exc:
            logger.warning("Fathom exa search failed: %s", exc)
            return AdapterOutcome(name=self.name, success=False, error=str(exc))
        results = data.get("results")
        if results is not None and not isinstance(results, list):
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="Exa search results was not an array",
            )
        return AdapterOutcome(
            name=self.name,
            success=True,
            rows=rows_from_exa(data, limit),
        )

    def extract(self, urls: list[str]) -> list[dict[str, Any]]:
        if not urls:
            return []
        if not self.enabled():
            return extract_fail(urls, "Exa is disabled. Turn on EXA_SEARCH_ENABLED.")
        if len(urls) > 100:
            return extract_fail(urls, "Exa contents accepts 1 to 100 URLs")
        try:
            payload = self.extract_body()
            settings = self.load_settings()
        except ValueError as exc:
            return extract_fail(urls, str(exc))
        payload["urls"] = list(urls)
        payload.pop("ids", None)
        timeout = float(settings["timeout"])
        try:
            data = self._post("/contents", payload, "extract")
        except TimeoutError as exc:
            logger.warning("Fathom exa extract timed out after %.0fs: %s", timeout, exc)
            return extract_fail(urls, f"exa timed out after {timeout:g}s: {exc}")
        except ValueError as exc:
            logger.warning("Fathom exa extract failed: %s", exc)
            return extract_fail(urls, str(exc))

        results = data.get("results")
        statuses = data.get("statuses")
        if results is not None and not isinstance(results, list):
            return extract_fail(urls, "Exa extract results was not an array")
        if statuses is not None and not isinstance(statuses, list):
            return extract_fail(urls, "Exa extract statuses was not an array")
        by_result = _index_items(results)
        by_status = _index_items(statuses)
        pages: list[dict[str, Any]] = []
        for url in urls:
            status = by_status.get(url)
            if status is not None and str(status.get("status") or "").strip().lower() not in {
                "",
                "success",
            }:
                pages.append(page_error(url, _compact_error(status)))
                continue
            item = by_result.get(url)
            if item is None:
                pages.append(page_error(url, "Exa contents returned no result for this URL"))
                continue
            title = str(item.get("title") or "").strip()
            pages.append(document(url, title, _extract_content(item)))
        return pages
