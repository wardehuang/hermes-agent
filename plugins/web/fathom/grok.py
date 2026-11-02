"""Grok adapter — Responses API with server-side web_search / x_search."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent.web_search_provider import get_provider_env

from plugins.web.fathom.common import (
    AdapterOutcome,
    load_config_section,
    nested_section,
    normalize_base_url,
    read_env,
    resolve_timeout,
    shared_timeout,
    timeout_outcome,
    trimmed_setting,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://wcpa.edmundvps.site:18453/v1"
DEFAULT_MODEL = "grok-4.20-multi-agent-0309"
DEFAULT_EFFORT = "high"
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)
_VALID_EFFORT = {"low", "medium", "high", "xhigh"}
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _now_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z")


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
    return default


def _flag(env_name: str, yaml_value: Any, default: bool) -> bool:
    """A set non-blank env wins. A blank env is not a saved choice."""
    raw = read_env(env_name)
    if raw is not None and raw.strip():
        return _as_bool(raw, default)
    if isinstance(yaml_value, bool):
        return yaml_value
    if isinstance(yaml_value, str) and yaml_value.strip():
        return _as_bool(yaml_value, default)
    return default


class GrokAdapter:
    name = "grok"

    def _section(self) -> dict[str, Any]:
        return nested_section(load_config_section(("web", "fathom")), "grok")

    def api_key(self) -> str:
        """Own key first. An explicit blank does not fall through to grok2api."""
        raw = read_env("GROK_SEARCH_API_KEY")
        if raw is not None:
            return raw.strip()
        section = self._section()
        if "api_key" in section:
            return str(section.get("api_key") or "").strip()
        key_env = section.get("key_env")
        if isinstance(key_env, str) and key_env.strip():
            pointed = read_env(key_env.strip())
            if pointed is None:
                return ""
            return pointed.strip()
        inherited = read_env("GROK2API_API_KEY")
        if inherited is not None and inherited.strip():
            return inherited.strip()
        provider = load_config_section(("providers", "grok2api"))
        provider_key_env = str(provider.get("key_env") or "").strip()
        if not provider_key_env:
            return ""
        pointed = read_env(provider_key_env)
        if pointed is None:
            return ""
        return pointed.strip()

    def base_url(self) -> str:
        """Own URL first. Unset may reuse providers.grok2api, then the shipped default."""
        raw = read_env("GROK_SEARCH_BASE_URL")
        section = self._section()
        if raw is not None:
            text = raw.strip()
            return normalize_base_url(text, "") if text else ""
        if "base_url" in section:
            text = str(section.get("base_url") or "").strip()
            return normalize_base_url(text, "") if text else ""
        provider = load_config_section(("providers", "grok2api"))
        inherited = str(provider.get("api") or provider.get("base_url") or "").strip()
        if inherited:
            return normalize_base_url(inherited, "")
        return normalize_base_url(DEFAULT_BASE_URL, "")

    def inputs(self) -> dict[str, str]:
        section = self._section()
        return {
            "api_key": self.api_key(),
            "base_url": self.base_url(),
            "model": trimmed_setting(
                "GROK_SEARCH_MODEL",
                section.get("model"),
                DEFAULT_MODEL,
            ),
            "effort": trimmed_setting(
                "GROK_SEARCH_EFFORT",
                section.get("effort"),
                DEFAULT_EFFORT,
            ).lower(),
        }

    def enabled(self) -> bool:
        return all(self.inputs().values())

    def is_available(self) -> bool:
        return self.enabled()

    def timeout(self) -> float:
        return float(self.load_settings()["timeout"])

    def load_settings(self) -> dict[str, Any]:
        fathom = load_config_section(("web", "fathom"))
        grok = nested_section(fathom, "grok")
        raw = self.inputs()
        effort = raw["effort"]
        if effort and effort not in _VALID_EFFORT:
            raise ValueError(
                f"Invalid web.fathom.grok.effort {effort!r}. "
                f"Use one of: {sorted(_VALID_EFFORT)}"
            )
        timeout = resolve_timeout(
            get_provider_env("GROK_SEARCH_TIMEOUT"),
            grok.get("timeout"),
            default=shared_timeout(fathom),
        )
        enable_web = _flag(
            "GROK_SEARCH_ENABLE_WEB_SEARCH",
            grok.get("enable_web_search"),
            True,
        )
        enable_x = _flag(
            "GROK_SEARCH_ENABLE_X_SEARCH",
            grok.get("enable_x_search"),
            False,
        )
        tools: list[dict[str, str]] = []
        if enable_web:
            tools.append({"type": "web_search"})
        if enable_x:
            tools.append({"type": "x_search"})
        return {
            "base_url": raw["base_url"],
            "model": raw["model"],
            "effort": effort,
            "timeout": timeout,
            "tools": tools,
            "api_key": raw["api_key"],
        }

    def search(self, query: str, limit: int) -> AdapterOutcome:
        if not self.enabled():
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="Grok skipped because an input is empty.",
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
                    "Set web.fathom.grok.enable_web_search and/or enable_x_search."
                ),
            )

        payload: dict[str, Any] = {
            "model": settings["model"],
            "input": [{"role": "user", "content": self._build_prompt(query, limit)}],
            "tools": tools,
            "reasoning": {"effort": settings["effort"]},
            "include": ["no_inline_citations"],
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {settings['api_key']}",
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
        if not isinstance(data, dict):
            return AdapterOutcome(
                name=self.name,
                success=False,
                error="Could not parse Grok Responses API reply as JSON",
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
            "sources, then independent secondary sources. Verify dates. "
            "Do not pick a winner and do not write a combined verdict. "
            "Return sources only. Do not stop after the first plausible page.\n"
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
        response_data: dict[str, Any],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
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
        response_data: dict[str, Any],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        text_blocks: list[str] = []
        annotations: list[dict[str, Any]] = []
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
    ) -> Optional[list[dict[str, Any]]]:
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
            normalized: list[dict[str, Any]] = []
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
        annotations: list[dict[str, Any]],
        joined_text: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
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
        response_data: dict[str, Any],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        output = response_data.get("output")
        if not isinstance(output, list):
            return []
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
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
