"""Intent judge for one Fathom search.

Adapter rows and answers are evidence. This pass ranks them with the live
main model, reads the shortlist, then emits one answer. A failed stage falls
back to the mechanical merge instead of failing the search.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from plugins.web.fathom.common import AdapterOutcome, merge_rows, normalize_url

logger = logging.getLogger(__name__)


def _now_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z")


READ_CAP = 8
PAGE_CHARS = 4000
SNIPPET_CHARS = 500
JUDGE_TIMEOUT = 120.0
JUDGE_MAX_TOKENS = 4096

Complete = Callable[[list[dict[str, str]]], tuple[str, str]]

_RANK_SYSTEM = (
    "You rank web search candidates for one query. "
    "Adapter answers are unverified hypotheses, not conclusions. "
    "Snippets are not full pages. "
    "The user message includes now (Asia/Shanghai). "
    "Relevance includes recency. When the query is about news, current events, "
    "products, prices, versions, or who holds a role now, a source whose stated "
    "date is years before now is off-intent if any newer on-topic source exists: "
    "omit it. If the query names a past date, that date is the target, not now. "
    "Do not invent dates. A snippet with no date is not evidence that it is current. "
    "A spec, definition, or primary document the query asks for may stay even if old. "
    "Return ONLY a JSON object with keys order and read. "
    "order is candidate URLs that match the query intent, best first. "
    "Omit off-topic and stale URLs. Do not invent URLs. "
    f"read is up to {READ_CAP} URLs from order whose full page should be opened, "
    "newest primary sources first."
)

_ANSWER_SYSTEM = (
    "You write one search answer from the evidence below. "
    "Adapter answers are hypotheses. Snippets are not full pages. "
    "Fetched pages are the evidence for those URLs. "
    "The user message includes now (Asia/Shanghai). "
    "Do not state a years-old article as the current fact. "
    "If the only evidence is old, say that it is old instead of presenting it as now. "
    "If the query names a past date, answer for that date. "
    "Do not invent dates. "
    "Unread rows may be used only as titles and snippets. "
    "If fetched pages disagree on a material fact, do not force one side. "
    "State what the pages agree on, and list the disagreement in conflicts. "
    "Write the answer in the same language as the query. "
    "Return ONLY a JSON object with keys answer, results, and conflicts. "
    "results is a list of {url, description}. description is 1-3 sentences "
    "grounded in that URL's fetched page, or in its snippets if the page was "
    "not fetched. Include the stated date when the page or snippet has one. "
    "conflicts is a list of {point, sides}. sides is a list of "
    "{claim, url}. conflicts is empty when the fetched pages do not disagree. "
    "Do not invent URLs."
)


@dataclass
class JudgeResult:
    response: Optional[dict[str, Any]]
    error: str = ""


def response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
                else:
                    text = getattr(part, "text", None)
                    if isinstance(text, str):
                        parts.append(text)
            joined = "".join(parts).strip()
            if joined:
                return joined
    output = getattr(response, "output", None)
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for part in content:
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if isinstance(text, str):
                    chunks.append(text)
        joined = "".join(chunks).strip()
        if joined:
            return joined
    return ""


def parse_json_object(text: str) -> Optional[dict[str, Any]]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def ordered_rows(
    pool: Sequence[dict[str, Any]],
    decision: dict[str, Any],
    limit: int,
) -> Optional[list[dict[str, Any]]]:
    by_url = {normalize_url(str(row.get("url") or "")): row for row in pool}
    order = decision.get("order")
    if not isinstance(order, list):
        return None
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in order:
        if not isinstance(url, str):
            continue
        key = normalize_url(url.strip())
        row = by_url.get(key)
        if row is None or not key or key in seen:
            continue
        seen.add(key)
        copied = dict(row)
        copied["position"] = len(picked) + 1
        picked.append(copied)
        if len(picked) >= limit:
            break
    return picked or None


def read_urls(
    decision: dict[str, Any],
    picked: Sequence[dict[str, Any]],
    cap: int,
) -> list[str]:
    by_key = {normalize_url(str(row.get("url") or "")): str(row["url"]) for row in picked}
    wanted = decision.get("read")
    if not isinstance(wanted, list):
        wanted = [row["url"] for row in picked]
    chosen: list[str] = []
    for url in wanted:
        if not isinstance(url, str):
            continue
        canonical = by_key.get(normalize_url(url.strip()))
        if canonical and canonical not in chosen:
            chosen.append(canonical)
        if len(chosen) >= cap:
            break
    return chosen


def apply_answer(
    rows: Sequence[dict[str, Any]],
    decision: dict[str, Any],
    allowed: Sequence[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    answer = str(decision.get("answer") or "").strip()
    if not answer:
        raise ValueError("judge answer missing")
    descriptions: dict[str, str] = {}
    results = decision.get("results")
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            description = str(item.get("description") or "").strip()
            key = normalize_url(url)
            if key and description:
                descriptions[key] = description
    known = {
        normalize_url(str(row.get("url") or ""))
        for row in (rows if allowed is None else allowed)
    }
    conflicts: list[dict[str, Any]] = []
    raw_conflicts = decision.get("conflicts")
    if isinstance(raw_conflicts, list):
        for item in raw_conflicts:
            if not isinstance(item, dict):
                continue
            point = str(item.get("point") or "").strip()
            sides = item.get("sides")
            if not point or not isinstance(sides, list) or not sides:
                continue
            kept_sides = []
            for side in sides:
                if not isinstance(side, dict):
                    continue
                claim = str(side.get("claim") or "").strip()
                url = str(side.get("url") or "").strip()
                if claim and url and normalize_url(url) in known:
                    kept_sides.append({"claim": claim, "url": url})
            if len(kept_sides) >= 2:
                conflicts.append({"point": point, "sides": kept_sides})
    rewritten: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        copied = dict(row)
        description = descriptions.get(normalize_url(str(row.get("url") or "")))
        if description:
            copied["description"] = description
        copied["position"] = index
        rewritten.append(copied)
    return answer, conflicts, rewritten


def _clip(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def _hypotheses(outcomes: Sequence[AdapterOutcome]) -> dict[str, str]:
    answers: dict[str, str] = {}
    for outcome in outcomes:
        if not outcome.success or outcome.timed_out:
            continue
        answer = str(outcome.extra.get("answer") or "").strip()
        if answer:
            answers[outcome.name] = answer
    return answers


def _candidate_block(pool: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    block = []
    for row in pool:
        snippets = []
        for snippet in row.get("snippets") or []:
            text = _clip(str(snippet.get("text") or ""), SNIPPET_CHARS)
            if text:
                snippets.append({"backend": snippet.get("backend"), "text": text})
        block.append(
            {
                "title": row.get("title") or "",
                "url": row.get("url") or "",
                "backends": list(row.get("backends") or []),
                "snippets": snippets,
            }
        )
    return block


def _live_main_route() -> tuple[str, str, dict[str, Any]]:
    """Provider and model of this turn's main runtime. Never a fixed model id."""
    from agent.auxiliary_client import _main_route_target, _normalize_main_runtime

    runtime = _normalize_main_runtime(None)
    provider, model, base_url, api_key, api_mode = _main_route_target(runtime, None)
    provider = str(provider or "").strip()
    model = str(model or "").strip()
    if not provider or not model or provider == "auto":
        raise RuntimeError("Fathom judge has no live main model")
    pinned = dict(runtime)
    pinned["provider"] = provider
    pinned["model"] = model
    if base_url:
        pinned["base_url"] = base_url
    if api_key:
        pinned["api_key"] = api_key
    if api_mode:
        pinned["api_mode"] = api_mode
    return provider, model, pinned


def _call_main(messages: list[dict[str, str]]) -> tuple[str, str]:
    """One completion on the live main model. No task name, so an auxiliary slot cannot replace it."""
    from agent.auxiliary_client import call_llm

    provider, model, runtime = _live_main_route()
    logger.info("Fathom judge main provider=%s model=%s", provider, model)
    api_key = runtime.get("api_key")
    response = call_llm(
        provider=provider,
        model=model,
        base_url=runtime.get("base_url") or None,
        api_key=api_key if isinstance(api_key, str) else None,
        api_mode=runtime.get("api_mode") or None,
        main_runtime=runtime,
        messages=messages,
        temperature=0,
        max_tokens=JUDGE_MAX_TOKENS,
        timeout=JUDGE_TIMEOUT,
    )
    reported = getattr(response, "model", None)
    return response_text(response), str(reported or model).strip()


def _pages_for(extract: Callable[[list[str]], list[dict[str, Any]]], urls: list[str]) -> list[dict[str, str]]:
    if not urls:
        return []
    pages = extract(urls)
    packed: list[dict[str, str]] = []
    for index, url in enumerate(urls):
        page = pages[index] if index < len(pages) and isinstance(pages[index], dict) else {}
        error = str(page.get("error") or "").strip()
        content = _clip(str(page.get("content") or ""), PAGE_CHARS)
        packed.append(
            {
                "url": url,
                "title": str(page.get("title") or "").strip(),
                "content": content,
                "error": error,
            }
        )
    return packed


def _meta(
    outcomes: Sequence[AdapterOutcome],
    *,
    judge: dict[str, Any],
    answer: str = "",
    conflicts: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
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
    fathom: dict[str, Any] = {
        "used": used,
        "timed_out": timed_out,
        "failed": failed,
        "judge": judge,
    }
    if answer:
        fathom["answer"] = answer
    if conflicts:
        fathom["conflicts"] = conflicts
    return fathom


def _payload(
    rows: list[dict[str, Any]],
    outcomes: Sequence[AdapterOutcome],
    *,
    judge: dict[str, Any],
    answer: str = "",
    conflicts: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "web": rows,
            "provider": "fathom",
            "fathom": _meta(outcomes, judge=judge, answer=answer, conflicts=conflicts),
        },
    }


def _interrupted() -> bool:
    try:
        from tools.interrupt import is_interrupted

        return bool(is_interrupted())
    except Exception:
        return False


def adjudicate(
    provider: Any,
    query: str,
    outcomes: Sequence[AdapterOutcome],
    output_limit: int,
    *,
    complete: Optional[Complete] = None,
    extract: Optional[Callable[[list[str]], list[dict[str, Any]]]] = None,
) -> JudgeResult:
    """Rank, read, and answer. ``response is None`` means use the mechanical merge."""
    complete_fn = complete or _call_main
    extract_fn = extract or provider.extract
    pool = merge_rows(outcomes, max(output_limit, 100))
    if not pool:
        return JudgeResult(None, "no candidates")

    rank_started = time.monotonic()
    rank_messages = [
        {"role": "system", "content": _RANK_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "now": _now_shanghai(),
                    "query": query,
                    "hypotheses": _hypotheses(outcomes),
                    "candidates": _candidate_block(pool),
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        rank_text, rank_model = complete_fn(rank_messages)
    except Exception as exc:
        logger.warning("Fathom judge rank call failed: %s", exc)
        return JudgeResult(None, f"rank call failed: {exc}")
    rank_ms = int((time.monotonic() - rank_started) * 1000)
    decision = parse_json_object(rank_text)
    if decision is None:
        return JudgeResult(None, "rank reply was not JSON")
    picked = ordered_rows(pool, decision, output_limit)
    if not picked:
        return JudgeResult(None, "rank order matched no candidates")
    urls = read_urls(decision, picked, READ_CAP)

    if _interrupted():
        return JudgeResult(None, "interrupted")

    extract_started = time.monotonic()
    try:
        pages = _pages_for(extract_fn, urls)
    except Exception as exc:
        logger.warning("Fathom judge extract failed: %s", exc)
        pages = [{"url": url, "title": "", "content": "", "error": str(exc)} for url in urls]
    extract_ms = int((time.monotonic() - extract_started) * 1000)

    if _interrupted():
        return JudgeResult(None, "interrupted")

    answer_started = time.monotonic()
    answer_messages = [
        {"role": "system", "content": _ANSWER_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "now": _now_shanghai(),
                    "query": query,
                    "hypotheses": _hypotheses(outcomes),
                    "ranked": _candidate_block(picked),
                    "pages": pages,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        answer_text, answer_model = complete_fn(answer_messages)
    except Exception as exc:
        logger.warning("Fathom judge answer call failed: %s", exc)
        judge = {
            "fallback": "rank_only",
            "error": f"answer call failed: {exc}",
            "model": rank_model,
            "rank_ms": rank_ms,
            "extract_ms": extract_ms,
            "answer_ms": 0,
            "read": urls,
        }
        logger.info(
            "Fathom judge query=%r pool=%d kept=%d read=%d rank_ms=%d extract_ms=%d answer_ms=0 model=%s fallback=rank_only",
            query,
            len(pool),
            len(picked),
            len(urls),
            rank_ms,
            extract_ms,
            rank_model,
        )
        return JudgeResult(_payload(picked, outcomes, judge=judge), judge["error"])
    answer_ms = int((time.monotonic() - answer_started) * 1000)
    model = answer_model or rank_model
    parsed = parse_json_object(answer_text)
    if parsed is None:
        judge = {
            "fallback": "rank_only",
            "error": "answer reply was not JSON",
            "model": model,
            "rank_ms": rank_ms,
            "extract_ms": extract_ms,
            "answer_ms": answer_ms,
            "read": urls,
        }
        logger.info(
            "Fathom judge query=%r pool=%d kept=%d read=%d rank_ms=%d extract_ms=%d answer_ms=%d model=%s fallback=rank_only",
            query,
            len(pool),
            len(picked),
            len(urls),
            rank_ms,
            extract_ms,
            answer_ms,
            model,
        )
        return JudgeResult(_payload(picked, outcomes, judge=judge), judge["error"])
    try:
        answer, conflicts, rows = apply_answer(picked, parsed, pool)
    except ValueError as exc:
        judge = {
            "fallback": "rank_only",
            "error": str(exc),
            "model": model,
            "rank_ms": rank_ms,
            "extract_ms": extract_ms,
            "answer_ms": answer_ms,
            "read": urls,
        }
        logger.info(
            "Fathom judge query=%r pool=%d kept=%d read=%d rank_ms=%d extract_ms=%d answer_ms=%d model=%s fallback=rank_only",
            query,
            len(pool),
            len(picked),
            len(urls),
            rank_ms,
            extract_ms,
            answer_ms,
            model,
        )
        return JudgeResult(_payload(picked, outcomes, judge=judge), str(exc))

    judge = {
        "fallback": None,
        "model": model,
        "rank_ms": rank_ms,
        "extract_ms": extract_ms,
        "answer_ms": answer_ms,
        "read": urls,
    }
    logger.info(
        "Fathom judge query=%r pool=%d kept=%d read=%d rank_ms=%d extract_ms=%d answer_ms=%d model=%s fallback=-",
        query,
        len(pool),
        len(rows),
        len(urls),
        rank_ms,
        extract_ms,
        answer_ms,
        model,
    )
    return JudgeResult(
        _payload(rows, outcomes, judge=judge, answer=answer, conflicts=conflicts)
    )
