"""Shared Fathom helpers: config, timeout, adapter outcomes, merge."""

from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from agent.web_search_provider import get_provider_env

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER_TIMEOUT = 120.0


@dataclass
class AdapterOutcome:
    name: str
    success: bool
    timed_out: bool = False
    error: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def load_config_section(path: tuple[str, ...]) -> dict[str, Any]:
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


def nested_section(parent: dict[str, Any], key: str) -> dict[str, Any]:
    node = parent.get(key)
    return node if isinstance(node, dict) else {}


def normalize_base_url(raw: str, default: str) -> str:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return default.rstrip("/")
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")


def configured_text(*candidates: Any) -> str:
    """First non-empty configured string. Callers must not pass code defaults."""
    for raw in candidates:
        if isinstance(raw, str):
            text = raw.strip()
        elif raw is None or isinstance(raw, (dict, list, bool)):
            continue
        else:
            text = str(raw).strip()
        if text:
            return text
    return ""


def configured_secret(env_name: str, section: dict[str, Any]) -> str:
    """Env var, then ``api_key``, then the env var named by ``key_env``. No implicit key."""
    direct = configured_text(get_provider_env(env_name))
    if direct:
        return direct
    inline = configured_text(section.get("api_key"))
    if inline:
        return inline
    key_env = configured_text(section.get("key_env"))
    if key_env:
        return configured_text(get_provider_env(key_env))
    return ""


def configured_base_url(*candidates: Any) -> str:
    raw = configured_text(*candidates)
    if not raw:
        return ""
    return normalize_base_url(raw, "")


def read_env(name: str) -> str | None:
    """Raw env value. ``None`` means unset; whitespace is kept for the caller to trim."""
    try:
        from hermes_cli.config import get_env_value

        value = get_env_value(name)
    except Exception as exc:
        try:
            from agent.secret_scope import UnscopedSecretError
        except ImportError:
            UnscopedSecretError = ()  # type: ignore[assignment,misc]
        if isinstance(exc, UnscopedSecretError):
            raise
        value = None
    if value is None:
        return None
    return str(value)


def trimmed_setting(env_name: str, yaml_value: Any, default: str = "") -> str:
    """Trim before use. A saved blank beats ``default``; an unset field uses it."""
    raw = read_env(env_name)
    if raw is not None:
        return raw.strip()
    if isinstance(yaml_value, str):
        return yaml_value.strip()
    if yaml_value is None:
        return default.strip()
    return str(yaml_value).strip()


def trimmed_secret(env_name: str, section: dict[str, Any], default: str = "") -> str:
    """Same trim rule for a key: explicit blank does not fall through to ``default``."""
    raw = read_env(env_name)
    if raw is not None:
        return raw.strip()
    if "api_key" in section:
        return str(section.get("api_key") or "").strip()
    key_env = section.get("key_env")
    if isinstance(key_env, str) and key_env.strip():
        pointed = read_env(key_env.strip())
        if pointed is None:
            return ""
        return pointed.strip()
    return default.strip()


def trimmed_base_url(env_name: str, yaml_value: Any, default: str) -> str:
    text = trimmed_setting(env_name, yaml_value, default)
    if not text:
        return ""
    return normalize_base_url(text, "")


def configured_object_present(env_name: str, yaml_value: Any, *, has_default: bool = False) -> bool:
    """True when the JSON input is usable after trim. Unset may use a shipped default."""
    raw = read_env(env_name)
    if raw is not None:
        return bool(raw.strip())
    if isinstance(yaml_value, dict):
        return bool(yaml_value)
    if isinstance(yaml_value, str):
        return bool(yaml_value.strip())
    return has_default


def resolve_timeout(*candidates: Any, default: float = DEFAULT_PROVIDER_TIMEOUT) -> float:
    for raw in candidates:
        if raw is None or raw == "":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout must be a number") from exc
        if value <= 0:
            raise ValueError("timeout must be > 0")
        return value
    return default


def shared_timeout(fathom: Optional[dict[str, Any]] = None) -> float:
    section = fathom if fathom is not None else load_config_section(("web", "fathom"))
    return resolve_timeout(
        get_provider_env("FATHOM_TIMEOUT"),
        section.get("timeout"),
        default=DEFAULT_PROVIDER_TIMEOUT,
    )


def normalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if not parts.netloc:
        return value.rstrip("/").lower()
    path = (parts.path.rstrip("/") or "/").lower()
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )


CANDIDATE_POOL = 20


def candidate_limit(output_limit: int) -> int:
    """How many rows each adapter should return before the final cap.

    The tool ``limit`` is the output cap. Adapters that slice to it first
    throw away candidates the judge never sees.
    """
    return min(100, max(int(output_limit), CANDIDATE_POOL))


def raise_request_count(body: dict[str, Any], key: str, floor: int, upper: int) -> None:
    """Raise a configured result count up to ``floor``, never above ``upper``.

    A configured value already above ``floor`` is left alone, so an explicit
    larger ``numResults`` / ``max_results`` still reaches the wire.
    """
    current = body.get(key)
    if isinstance(current, bool) or not isinstance(current, int):
        current = 0
    body[key] = max(1, min(upper, max(current, floor)))


def _snippet_description(snippets: list[dict[str, str]], fallback: str) -> str:
    texts: list[str] = []
    labeled: list[str] = []
    for snippet in snippets:
        text = snippet.get("text") or ""
        if not text:
            continue
        if text not in texts:
            texts.append(text)
        labeled.append(f"[{snippet['backend']}] {text}")
    if len(texts) > 1:
        return "\n".join(labeled)
    if texts:
        return texts[0]
    return fallback


def _public_row(item: dict[str, Any], position: int) -> dict[str, Any]:
    snippets = list(item.get("snippets") or [])
    row = {
        "title": item["title"],
        "url": item["url"],
        "description": _snippet_description(snippets, item["description"]),
        "position": position,
        "backends": list(item["backends"]),
    }
    if snippets:
        row["snippets"] = snippets
    return row


def merge_rows(outcomes: Sequence[AdapterOutcome], limit: int) -> list[dict[str, Any]]:
    """Dedupe by URL. Multi-backend hits first, then round-robin uniques."""
    ranked: dict[str, dict[str, Any]] = {}
    order = 0
    backend_order: list[str] = []
    for outcome in outcomes:
        if not outcome.success or outcome.timed_out:
            continue
        if outcome.name not in backend_order:
            backend_order.append(outcome.name)
        for row in outcome.rows:
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            key = normalize_url(url) or url
            existing = ranked.get(key)
            text = str(row.get("description") or "").strip()
            if existing is None:
                order += 1
                ranked[key] = {
                    "title": str(row.get("title") or "").strip(),
                    "url": url,
                    "description": text,
                    "position": order,
                    "backends": [outcome.name],
                    "snippets": (
                        [{"backend": outcome.name, "text": text}] if text else []
                    ),
                    "_agree": 1,
                    "_order": order,
                    "_backend": outcome.name,
                }
                continue
            existing["_agree"] += 1
            if outcome.name not in existing["backends"]:
                existing["backends"].append(outcome.name)
            if text and not any(
                snippet["backend"] == outcome.name and snippet["text"] == text
                for snippet in existing["snippets"]
            ):
                existing["snippets"].append({"backend": outcome.name, "text": text})
            if not existing["title"]:
                existing["title"] = str(row.get("title") or "").strip()
            if not existing["description"]:
                existing["description"] = text

    agreed = sorted(
        [item for item in ranked.values() if int(item["_agree"]) >= 2],
        key=lambda item: (-int(item["_agree"]), int(item["_order"])),
    )
    uniques_by_backend: dict[str, list[dict[str, Any]]] = {
        name: [] for name in backend_order
    }
    for item in ranked.values():
        if int(item["_agree"]) >= 2:
            continue
        uniques_by_backend.setdefault(str(item["_backend"]), []).append(item)
    for _name, rows in uniques_by_backend.items():
        rows.sort(key=lambda item: int(item["_order"]))

    out: list[dict[str, Any]] = []
    for item in agreed:
        out.append(_public_row(item, len(out) + 1))
        if len(out) >= limit:
            return out

    queues = [uniques_by_backend[name] for name in backend_order if uniques_by_backend.get(name)]
    index = 0
    while queues and len(out) < limit:
        current = queues[index % len(queues)]
        if current:
            out.append(_public_row(current.pop(0), len(out) + 1))
        if not current:
            queues.pop(index % len(queues))
            if queues:
                index = index % len(queues)
            continue
        index += 1
    return out


def dispatch_adapters(
    jobs: Sequence[tuple[str, float, Callable[[], AdapterOutcome]]],
) -> list[AdapterOutcome]:
    """Run adapters in parallel. Each job carries its own timeout.

    The callable must already bound HTTP I/O to *timeout*. This wall is a
    second cut: a hung job is marked timed-out and its rows are dropped.

    Each job runs in its own copy of the submitter's contextvars. Python 3.14's
    ThreadPoolExecutor does not propagate them, so a multiplexed host would
    fail-close credential reads (the secret-scope ContextVar is empty on the
    worker while the process-global multiplex flag stays set).
    """
    if not jobs:
        return []

    outcomes: list[AdapterOutcome] = []
    wall = max(timeout for _name, timeout, _call in jobs) + 2.0
    pool = ThreadPoolExecutor(max_workers=len(jobs))
    try:
        future_map = {}
        for name, timeout, call in jobs:
            ctx = contextvars.copy_context()
            future_map[pool.submit(ctx.run, _invoke_job, name, timeout, call)] = (
                name,
                timeout,
            )
        done, pending = wait(future_map, timeout=wall)
        for future in done:
            name, timeout = future_map[future]
            try:
                outcomes.append(future.result())
            except Exception as exc:
                logger.warning("Fathom adapter %s crashed: %s", name, exc)
                outcomes.append(
                    AdapterOutcome(name=name, success=False, error=str(exc))
                )
        for future in pending:
            name, timeout = future_map[future]
            logger.warning("Fathom adapter %s exceeded %ss wall", name, timeout)
            outcomes.append(
                AdapterOutcome(
                    name=name,
                    success=False,
                    timed_out=True,
                    error=f"{name} timed out after {timeout:g}s",
                )
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return outcomes


def _invoke_job(
    name: str,
    timeout: float,
    call: Callable[[], AdapterOutcome],
) -> AdapterOutcome:
    try:
        outcome = call()
    except Exception as exc:
        logger.warning("Fathom adapter %s raised: %s", name, exc)
        return AdapterOutcome(name=name, success=False, error=str(exc))
    if outcome.timed_out and not outcome.error:
        outcome.error = f"{name} timed out after {timeout:g}s"
    return outcome


def timeout_outcome(name: str, timeout: float, exc: BaseException) -> AdapterOutcome:
    return AdapterOutcome(
        name=name,
        success=False,
        timed_out=True,
        error=f"{name} timed out after {timeout:g}s: {exc}",
    )
