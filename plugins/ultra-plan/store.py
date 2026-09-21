"""Per-session Ultra Plan mode — JSON file shared by hooks and the dashboard.

State lives in ``<hermes home>/plugin-data/ultra-plan/state.json`` — never in
the plugin install directory.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_MODE",
    "ModeStore",
    "durable_session_id",
    "load_store",
    "STORE_MODULE_NAME",
]

STORE_MODULE_NAME = "ultra_plan_store"

DEFAULT_MODE = "agent"
_VALID_MODES = ("agent", "plan")
SESSION_TTL_SECONDS = 30 * 24 * 3600
logger = logging.getLogger("plugins.ultra-plan")

# Gateway runtime ids are uuid.uuid4().hex[:8] (tui_gateway.methods_session._new_runtime_ids).
# AIAgent.session_id is the stored key from new_session_id() (`YYYYMMDD_HHMMSS_<hex6>`).
# Keying mode by the runtime id makes every hook lookup miss and the session stays Agent.
_RUNTIME_SID_RE = re.compile(r"^[0-9a-f]{8}$")


def durable_session_id(value: Any) -> str | None:
    """Return a stored session id, or None for missing / gateway runtime ids."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _RUNTIME_SID_RE.fullmatch(text):
        return None
    return text[:200]


def _data_dir(name: str) -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir

        return Path(plugin_data_dir(name))
    except Exception:
        pass
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    root = Path(home) / "plugin-data" / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clean_pending(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or "").strip().lower()
    if action not in {"continue", "build"}:
        return None
    plan_file = str(raw.get("plan_file") or "").strip()[:400]
    comments_in = raw.get("comments")
    comments: list[dict[str, str]] = []
    if isinstance(comments_in, list):
        for item in comments_in[:40]:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote") or "").strip()[:2000]
            body = str(item.get("body") or "").strip()[:4000]
            if not quote and not body:
                continue
            comments.append({"quote": quote, "body": body})
    return {"action": action, "plan_file": plan_file, "comments": comments}


class ModeStore:
    """Thread-safe, file-backed mode + one-shot Continue/Build payload."""

    def __init__(self, name: str = "ultra-plan", ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self.name = name
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._path = _data_dir(name) / "state.json"
        self._default = DEFAULT_MODE
        self._next: str | None = None
        self._sessions: dict[str, dict[str, Any]] = {}
        self._mtime = 0.0
        self._load(force=True)

    def _load(self, force: bool = False) -> None:
        with self._lock:
            try:
                stat = self._path.stat()
            except OSError:
                return
            if not force and stat.st_mtime == self._mtime:
                return
            self._mtime = stat.st_mtime
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            default = data.get("default")
            self._default = default if default in _VALID_MODES else DEFAULT_MODE
            nxt = data.get("next")
            self._next = nxt if nxt in _VALID_MODES else None
            sessions = data.get("sessions")
            parsed: dict[str, dict[str, Any]] = {}
            for sid, rec in (sessions.items() if isinstance(sessions, dict) else []):
                if not isinstance(rec, dict) or rec.get("mode") not in _VALID_MODES:
                    continue
                parsed[str(sid)] = {
                    "mode": rec.get("mode"),
                    "updated_at": float(rec.get("updated_at") or 0.0),
                    "pending": _clean_pending(rec.get("pending")),
                }
            self._sessions = parsed

    def _save(self) -> None:
        with self._lock:
            now = time.time()
            cutoff = now - self.ttl_seconds
            self._sessions = {
                sid: rec for sid, rec in self._sessions.items() if rec["updated_at"] >= cutoff
            }
            payload = {
                "version": 1,
                "default": self._default,
                "next": self._next,
                "sessions": self._sessions,
            }
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, self._path)
                self._mtime = self._path.stat().st_mtime
            except OSError:
                pass

    def get_mode(self, session_id: str | None, *, consume_next: bool = False) -> str:
        with self._lock:
            self._load()
            sid = durable_session_id(session_id)
            if sid:
                rec = self._sessions.get(sid)
                if rec and rec.get("mode") in _VALID_MODES:
                    return str(rec["mode"])
                if consume_next and self._next in _VALID_MODES:
                    mode = self._next
                    self._next = None
                    self._sessions[sid] = {
                        "mode": mode,
                        "updated_at": time.time(),
                        "pending": None,
                    }
                    self._save()
                    return mode
            if self._next in _VALID_MODES and not sid:
                return self._next
            return self._default

    def get_default(self) -> str:
        with self._lock:
            self._load()
            return self._default

    def get_next(self) -> str | None:
        with self._lock:
            self._load()
            return self._next

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._load()
            return {
                "default": self._default,
                "next": self._next,
                "sessions": {sid: rec["mode"] for sid, rec in self._sessions.items()},
            }

    def set_mode(self, session_id: str | None, mode: str) -> str:
        if mode not in _VALID_MODES:
            raise ValueError(f"unknown mode: {mode!r}")
        with self._lock:
            self._load()
            sid = durable_session_id(session_id)
            if session_id and not sid:
                logger.info("set_mode dropping runtime session id %s; using next", session_id)
            if sid:
                rec = self._sessions.get(sid) or {}
                rec["mode"] = mode
                rec["updated_at"] = time.time()
                rec.setdefault("pending", None)
                self._sessions[sid] = rec
            else:
                self._next = mode
            self._save()
            return mode

    def set_pending(self, session_id: str, pending: dict[str, Any] | None) -> None:
        sid = durable_session_id(session_id)
        if not sid:
            raise ValueError("session_id required")
        cleaned = _clean_pending(pending) if pending else None
        with self._lock:
            self._load()
            rec = self._sessions.get(sid) or {
                "mode": self._default,
                "updated_at": time.time(),
                "pending": None,
            }
            rec["pending"] = cleaned
            rec["updated_at"] = time.time()
            self._sessions[sid] = rec
            self._save()

    def pop_pending(self, session_id: str | None) -> dict[str, Any] | None:
        sid = durable_session_id(session_id)
        if not sid:
            return None
        with self._lock:
            self._load()
            rec = self._sessions.get(sid)
            if not rec:
                return None
            pending = rec.get("pending")
            if pending:
                rec["pending"] = None
                rec["updated_at"] = time.time()
                self._sessions[sid] = rec
                self._save()
            return pending if isinstance(pending, dict) else None

    def clear_session(self, session_id: str) -> None:
        sid = durable_session_id(session_id)
        if not sid:
            return
        with self._lock:
            self._load()
            self._sessions.pop(sid, None)
            self._save()


def load_store(name: str = "ultra-plan") -> ModeStore:
    existing = sys.modules.get(STORE_MODULE_NAME)
    store = getattr(existing, "_STORE", None) if existing is not None else None
    if isinstance(store, ModeStore):
        return store
    store = ModeStore(name)
    if existing is None:
        holder = sys.modules.setdefault(STORE_MODULE_NAME, sys.modules[__name__])
        setattr(holder, "_STORE", store)
    else:
        setattr(existing, "_STORE", store)
    return store
