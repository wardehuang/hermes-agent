"""Grok adapter — Responses API with server-side web_search / x_search."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from agent.web_search_provider import get_provider_env

from plugins.web.fathom.common import (
    AdapterOutcome,
    as_bool,
    load_config_section,
    normalize_base_url,
    resolve_timeout,
    shared_timeout,
    timeout_outcome,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://wcpa.edmundvps.site:18453/v1"
DEFAULT_MODEL = "grok-4.20-multi-agent-0309"
DEFAULT_EFFORT = "high"
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)
_VALID_EFFORT = {"low", "medium", "high", "xhigh"}


def _now_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z")


class GrokAdapter:
    name = "grok"

    def is_available(self) -> bool:
        return bool(self.api_key())

    def timeout(self) -> float:
        return float(self.load_settings()["timeout"])

    def api_key(self) -> str:
        direct = get_provider_env("GROK_SEARCH_API_KEY")
        if direct:
            return direct
        fathom = load_config_section(("web", "fathom"))
        key_env = str(fathom.get("key_env") or "").strip()
        if key_env:
            value = get_provider_env(key_env)
            if value:
                return value
        grok2api = get_provider_env("GROK2API_API_KEY")
        if grok2api:
            return grok2api
        provider = load_config_section(("providers", "grok2api"))
        provider_key_env = str(provider.get("key_env") or "").strip()
        if provider_key_env:
            return get_provider_env(provider_key_env)
        return ""

    def load_settings(self) -> Dict[str, Any]:
        fathom = load_config_section(("web", "fathom"))
        grok2api = load_config_section(("providers", "grok2api"))
        grok2api_url = str(grok2api.get("api") or grok2api.get("base_url") or "").strip()

        base_url = normalize_base_url(
            get_provider_env("GROK_SEARCH_BASE_URL")
            or str(fathom.get("base_url") or grok2api_url or DEFAULT_BASE_URL),
            DEFAULT_BASE_URL,
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
        timeout = resolve_timeout(
            get_provider_env("GROK_SEARCH_TIMEOUT"),
            fathom.get("timeout"),
            default=shared_timeout(fathom),
        )

        enable_web = as_bool(fathom.get("enable_web_search", True), True)
        enable_x = as_bool(fathom.get("enable_x_search", True), True)
        env_web = get_provider_env("GROK_SEARCH_ENABLE_WEB_SEARCH")
        env_x = get_provider_env("GROK_SEARCH_ENABLE_X_SEARCH")
        if env_web:
            enable_web = as_bool(env_web, enable_web)
        if env_x:
            enable_x = as_bool(env_x, enable_x)

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

    def search(self, query: str, limit: int) -> AdapterOutcome:
        api_key = self.api_key()
        if not api_key:
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="No Grok credentials. Set GROK_SEARCH_API_KEY or GROK2API_API_KEY.",
            )

        try:
            settings = self.load_settings()
        except ValueError as exc:
            return AdapterOutcome(name=self.name, success=False, error=str(exc))

        tools = settings["tools"]
        timeout = float(settings["timeout"])
        if not tools:
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=(
                    "Grok has no tools enabled. "
                    "Set web.fathom.enable_web_search and/or web.fathom.enable_x_search."
                ),
            )

        payload: Dict[str, Any] = {
            "model": settings["model"],
            "input": [{"role": "user", "content": self._build_prompt(query, limit)}],
            "tools": tools,
            "reasoning": {"effort": settings["effort"]},
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
            return AdapterOutcome(name=self.name, success=False, error="httpx is not installed")

        logger.info(
            "Fathom grok via %s model=%s effort=%s timeout=%.0fs limit=%d query=%r",
            settings["base_url"],
            settings["model"],
            settings["effort"],
            timeout,
            limit,
            query,
        )

        try:
            resp = httpx.post(
                f"{settings['base_url']}/responses",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning("Fathom grok timed out after %.0fs: %s", timeout, exc)
            return timeout_outcome(self.name, timeout, exc)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = ""
            try:
                body = exc.response.text[:400] if exc.response is not None else ""
            except Exception:
                body = ""
            logger.warning("Fathom grok HTTP %d: %s", status, body)
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=f"Grok returned HTTP {status}: {body}".rstrip(),
            )
        except httpx.RequestError as exc:
            logger.warning("Fathom grok request error: %s", exc)
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=f"Could not reach Grok: {exc}",
            )

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Fathom grok bad JSON: %s", exc)
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="Could not parse Grok Responses API reply as JSON",
            )

        api_error = data.get("error") if isinstance(data, dict) else None
        if isinstance(api_error, dict):
            err_msg = api_error.get("message") or api_error.get("code") or "unknown error"
            return AdapterOutcome(
                name=self.name,
                success=False,
                error=f"Grok returned an error: {err_msg}",
            )

        rows = self._extract_results(data, limit=limit)
        return AdapterOutcome(name=self.name, success=True, rows=rows)

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
