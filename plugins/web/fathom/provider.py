"""Fathom — multi-provider web search.

Grok is the first live backend. ChatGPT, Exa, and Tavily land next.

Grok routes through an OpenAI-compatible Responses API with server-side
``web_search`` and ``x_search``. Default model is
``grok-4.20-multi-agent-0309`` with ``reasoning.effort: high`` (16-agent).

Config::

    web:
      search_backend: "fathom"
      fathom:
        base_url: "http://wcpa.edmundvps.site:18453/v1"
        model: "grok-4.20-multi-agent-0309"
        effort: "high"
        timeout: 600
        enable_web_search: true
        enable_x_search: true
        key_env: "GROK2API_API_KEY"

Env overrides (Desktop Tools panel can write these):

    GROK_SEARCH_API_KEY
    GROK_SEARCH_BASE_URL
    GROK_SEARCH_MODEL
    GROK_SEARCH_EFFORT
    GROK_SEARCH_TIMEOUT

If ``web.fathom.base_url`` / API key are unset, Fathom reuses
``providers.grok2api.api`` and ``providers.grok2api.key_env``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from agent.web_search_provider import WebSearchProvider, get_provider_env

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://wcpa.edmundvps.site:18453/v1"
DEFAULT_MODEL = "grok-4.20-multi-agent-0309"
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT = 600
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)
_VALID_EFFORT = {"low", "medium", "high", "xhigh"}


def _now_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z")


def _normalize_base_url(raw: str) -> str:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return DEFAULT_BASE_URL
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _load_config_section(path: tuple[str, ...]) -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        node: Any = load_config()
    except Exception as exc:
        logger.debug("Could not load config for %s: %s", ".".join(path), exc)
        return {}
    for key in path:
        if not isinstance(node, dict):
            return {}
        node = node.get(key)
    return node if isinstance(node, dict) else {}


class FathomWebSearchProvider(WebSearchProvider):
    """Multi-provider search backend. Grok is the first live adapter."""

    @property
    def name(self) -> str:
        return "fathom"

    @property
    def display_name(self) -> str:
        return "Fathom"

    def is_available(self) -> bool:
        return bool(self._api_key())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Fathom",
            "badge": "ensemble",
            "tag": (
                "Multi-provider web search. Grok is live; "
                "ChatGPT, Exa, and Tavily come next."
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
                    "default": DEFAULT_BASE_URL,
                },
                {
                    "key": "GROK_SEARCH_MODEL",
                    "prompt": "Grok model id",
                    "default": DEFAULT_MODEL,
                },
                {
                    "key": "GROK_SEARCH_EFFORT",
                    "prompt": "Grok reasoning.effort: low|medium|high|xhigh (high = 16 agents)",
                    "default": DEFAULT_EFFORT,
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

        api_key = self._api_key()
        if not api_key:
            return {
                "success": False,
                "error": (
                    "No Fathom credentials. Set GROK_SEARCH_API_KEY "
                    "or GROK2API_API_KEY."
                ),
            }

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 100))

        try:
            cfg = self._load_settings()
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        tools = cfg["tools"]
        if not tools:
            return {
                "success": False,
                "error": (
                    "Fathom has no tools enabled. "
                    "Set web.fathom.enable_web_search and/or web.fathom.enable_x_search."
                ),
            }

        payload: Dict[str, Any] = {
            "model": cfg["model"],
            "input": [{"role": "user", "content": self._build_prompt(query, limit)}],
            "tools": tools,
            "reasoning": {"effort": cfg["effort"]},
            "include": ["no_inline_citations"],
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            import httpx
        except ImportError:
            return {"success": False, "error": "httpx is not installed"}

        logger.info(
            "Fathom via %s model=%s effort=%s limit=%d query=%r",
            cfg["base_url"],
            cfg["model"],
            cfg["effort"],
            limit,
            query,
        )

        try:
            resp = httpx.post(
                f"{cfg['base_url']}/responses",
                headers=headers,
                json=payload,
                timeout=cfg["timeout"],
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = ""
            try:
                body = exc.response.text[:400] if exc.response is not None else ""
            except Exception:
                body = ""
            logger.warning("Fathom HTTP %d: %s", status, body)
            return {
                "success": False,
                "error": f"Fathom returned HTTP {status}: {body}".rstrip(),
            }
        except httpx.RequestError as exc:
            logger.warning("Fathom request error: %s", exc)
            return {"success": False, "error": f"Could not reach Fathom: {exc}"}

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Fathom bad JSON: %s", exc)
            return {
                "success": False,
                "error": "Could not parse Responses API reply as JSON",
            }

        api_error = data.get("error") if isinstance(data, dict) else None
        if isinstance(api_error, dict):
            err_msg = api_error.get("message") or api_error.get("code") or "unknown error"
            return {"success": False, "error": f"Fathom returned an error: {err_msg}"}

        return {"success": True, "data": {"web": self._extract_results(data, limit=limit)}}

    def _api_key(self) -> str:
        direct = get_provider_env("GROK_SEARCH_API_KEY")
        if direct:
            return direct
        fathom = _load_config_section(("web", "fathom"))
        key_env = str(fathom.get("key_env") or "").strip()
        if key_env:
            value = get_provider_env(key_env)
            if value:
                return value
        grok2api = get_provider_env("GROK2API_API_KEY")
        if grok2api:
            return grok2api
        provider = _load_config_section(("providers", "grok2api"))
        provider_key_env = str(provider.get("key_env") or "").strip()
        if provider_key_env:
            return get_provider_env(provider_key_env)
        return ""

    def _load_settings(self) -> Dict[str, Any]:
        fathom = _load_config_section(("web", "fathom"))
        grok2api = _load_config_section(("providers", "grok2api"))
        grok2api_url = str(grok2api.get("api") or grok2api.get("base_url") or "").strip()

        base_url = _normalize_base_url(
            get_provider_env("GROK_SEARCH_BASE_URL")
            or str(fathom.get("base_url") or grok2api_url or DEFAULT_BASE_URL)
        )
        model = (
            get_provider_env("GROK_SEARCH_MODEL")
            or str(fathom.get("model") or DEFAULT_MODEL)
        ).strip() or DEFAULT_MODEL
        effort_raw = (
            get_provider_env("GROK_SEARCH_EFFORT")
            or str(fathom.get("effort") or DEFAULT_EFFORT)
        ).strip().lower()
        if effort_raw not in _VALID_EFFORT:
            raise ValueError(
                f"Invalid web.fathom.effort {effort_raw!r}. Use one of: {sorted(_VALID_EFFORT)}"
            )
        try:
            timeout = float(
                get_provider_env("GROK_SEARCH_TIMEOUT")
                or fathom.get("timeout")
                or DEFAULT_TIMEOUT
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("web.fathom.timeout must be a number") from exc

        enable_web = _as_bool(fathom.get("enable_web_search", True), True)
        enable_x = _as_bool(fathom.get("enable_x_search", True), True)
        env_web = get_provider_env("GROK_SEARCH_ENABLE_WEB_SEARCH")
        env_x = get_provider_env("GROK_SEARCH_ENABLE_X_SEARCH")
        if env_web:
            enable_web = _as_bool(env_web, enable_web)
        if env_x:
            enable_x = _as_bool(env_x, enable_x)

        tools: List[Dict[str, str]] = []
        if enable_web:
            tools.append({"type": "web_search"})
        if enable_x:
            tools.append({"type": "x_search"})

        return {
            "base_url": base_url,
            "model": model,
            "effort": effort_raw,
            "timeout": timeout,
            "tools": tools,
        }

    @staticmethod
    def _build_prompt(query: str, limit: int) -> str:
        now = _now_shanghai()
        return (
            f"Current local datetime: {now} (Asia/Shanghai).\n"
            "You are a deep web research searcher. Accuracy, recency, and completeness "
            "matter more than brevity or token cost.\n"
            "Use the web_search tool. Also use x_search when the query involves news, "
            "announcements, social discussion, or anything time-sensitive on X.\n"
            "Split the query into multiple search angles. Prefer official / first-party "
            "sources, then independent secondary sources. Verify dates. If sources conflict, "
            "keep both sides. Do not stop after the first plausible answer.\n"
            "Return ONLY a single JSON object — no prose, no markdown fences, no inline "
            "citation links — matching this schema:\n\n"
            '{"results": [{"title": "string", "url": "string", '
            '"description": "1-3 sentence summary with date if known"}]}\n\n'
            f"Return at most {limit} high-value sources, ordered by usefulness. "
            "Use absolute https:// URLs. If nothing usable exists, return "
            '{"results": []}.\n\n'
            f"Query: {query}"
        )

    @classmethod
    def _extract_results(
        cls,
        response_data: Dict[str, Any],
        *,
        limit: int,
    ) -> List[Dict[str, Any]]:
        text_blocks, annotations = cls._collect_output_text(response_data)
        for block in text_blocks:
            parsed = cls._try_parse_json_results(block, limit=limit)
            if parsed:
                return parsed

        if annotations:
            joined_text = "\n".join(text_blocks)
            annotation_results = cls._results_from_annotations(
                annotations, joined_text, limit=limit
            )
            if annotation_results:
                return annotation_results

        tool_results = cls._results_from_tool_calls(response_data, limit=limit)
        if tool_results:
            return tool_results

        citations = response_data.get("citations") or []
        if isinstance(citations, list):
            return [
                {
                    "title": "",
                    "url": str(url),
                    "description": "",
                    "position": index + 1,
                }
                for index, url in enumerate(citations[:limit])
                if isinstance(url, str) and url.strip()
            ]
        return []

    @staticmethod
    def _collect_output_text(
        response_data: Dict[str, Any],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        text_blocks: List[str] = []
        annotations: List[Dict[str, Any]] = []
        output = response_data.get("output")
        if not isinstance(output, list):
            return text_blocks, annotations

        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for chunk in content:
                if not isinstance(chunk, dict) or chunk.get("type") != "output_text":
                    continue
                text = chunk.get("text")
                if isinstance(text, str) and text.strip():
                    text_blocks.append(text)
                chunk_annotations = chunk.get("annotations")
                if isinstance(chunk_annotations, list):
                    for ann in chunk_annotations:
                        if isinstance(ann, dict):
                            annotations.append(ann)
        return text_blocks, annotations

    @staticmethod
    def _try_parse_json_results(
        text: str,
        *,
        limit: int,
    ) -> Optional[List[Dict[str, Any]]]:
        candidates = [text]
        match = _JSON_BLOCK_RE.search(text)
        if match and match.group(0) != text:
            candidates.append(match.group(0))

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue
            results = parsed.get("results")
            if not isinstance(results, list):
                continue
            normalized: List[Dict[str, Any]] = []
            for row in results[:limit]:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url", "")).strip()
                if not url:
                    continue
                normalized.append(
                    {
                        "title": str(row.get("title", "")).strip(),
                        "url": url,
                        "description": str(row.get("description", "")).strip(),
                        "position": len(normalized) + 1,
                    }
                )
            if normalized:
                return normalized
        return None

    @staticmethod
    def _results_from_annotations(
        annotations: List[Dict[str, Any]],
        joined_text: str,
        *,
        limit: int,
    ) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        results: List[Dict[str, Any]] = []
        for ann in annotations:
            if ann.get("type") not in {"url_citation", "citation"}:
                continue
            url = str(ann.get("url", "")).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            description = ""
            start = ann.get("start_index")
            end = ann.get("end_index")
            if (
                isinstance(start, int)
                and isinstance(end, int)
                and 0 <= start < end <= len(joined_text)
            ):
                window_start = max(0, start - 200)
                description = joined_text[window_start:start].strip()
                if len(description) > 200:
                    description = description[-200:].strip()
            results.append(
                {
                    "title": str(ann.get("title", "")).strip(),
                    "url": url,
                    "description": description,
                    "position": len(results) + 1,
                }
            )
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _results_from_tool_calls(
        response_data: Dict[str, Any],
        *,
        limit: int,
    ) -> List[Dict[str, Any]]:
        output = response_data.get("output")
        if not isinstance(output, list):
            return []
        seen: set[str] = set()
        results: List[Dict[str, Any]] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") not in {"web_search_call", "x_search_call"}:
                continue
            action = item.get("action")
            sources = []
            if isinstance(action, dict):
                raw_sources = action.get("sources")
                if isinstance(raw_sources, list):
                    sources = raw_sources
            for source in sources:
                url = ""
                title = ""
                description = ""
                if isinstance(source, str):
                    url = source.strip()
                elif isinstance(source, dict):
                    url = str(source.get("url", "")).strip()
                    title = str(source.get("title", "")).strip()
                    description = str(
                        source.get("description") or source.get("snippet") or ""
                    ).strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(
                    {
                        "title": title,
                        "url": url,
                        "description": description,
                        "position": len(results) + 1,
                    }
                )
                if len(results) >= limit:
                    return results
        return results
