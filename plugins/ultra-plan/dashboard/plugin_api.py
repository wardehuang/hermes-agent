"""Ultra Plan backend — REST the desktop half talks to via ctx.rest."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

PLUGIN_NAME = "ultra-plan"
VERSION = "1.0.0"
STORE_MODULE = "ultra_plan_store"
_PLUGIN_DIR = Path(__file__).resolve().parent.parent

MODES = ("agent", "plan")
DEFAULT_MODE = "agent"

router = APIRouter()


def _store():
    mod = sys.modules.get(STORE_MODULE)
    if mod is None or not hasattr(mod, "load_store"):
        spec = importlib.util.spec_from_file_location(STORE_MODULE, _PLUGIN_DIR / "store.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("ultra-plan: cannot load store.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[STORE_MODULE] = mod
        spec.loader.exec_module(mod)
    return mod.load_store(PLUGIN_NAME)


def _clean_session_id(value: Any) -> Optional[str]:
    _store()
    mod = sys.modules.get(STORE_MODULE)
    fn = getattr(mod, "durable_session_id", None) if mod is not None else None
    if not callable(fn):
        raise RuntimeError("ultra-plan: durable_session_id missing")
    return fn(value)


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "plugin": PLUGIN_NAME, "version": VERSION}


@router.get("/state")
async def state() -> dict:
    snapshot = _store().snapshot()
    return {
        "ok": True,
        "version": VERSION,
        "modes": list(MODES),
        "default": snapshot["default"],
        "next": snapshot.get("next"),
        "sessions": snapshot["sessions"],
    }


@router.get("/mode")
async def read_mode(session_id: Optional[str] = None) -> dict:
    store = _store()
    sid = _clean_session_id(session_id)
    return {
        "ok": True,
        "session_id": sid,
        "mode": store.get_mode(sid),
        "default": store.get_default(),
        "next": store.get_next(),
    }


@router.post("/mode")
async def write_mode(body: dict = Body(default_factory=dict)) -> Any:
    payload = body if isinstance(body, dict) else {}
    mode = str(payload.get("mode") or "").strip().lower()
    sid = _clean_session_id(payload.get("session_id"))
    if mode not in MODES:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"unknown mode {mode!r}", "modes": list(MODES)},
        )
    try:
        store = _store()
        store.set_mode(sid, mode)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
    return {
        "ok": True,
        "session_id": sid,
        "mode": mode,
        "default": store.get_default(),
        "next": store.get_next(),
    }


@router.post("/action")
async def write_action(body: dict = Body(default_factory=dict)) -> Any:
    payload = body if isinstance(body, dict) else {}
    action = str(payload.get("action") or "").strip().lower()
    sid = _clean_session_id(payload.get("session_id"))
    if action not in {"continue", "build"}:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"unknown action {action!r}"},
        )
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    try:
        store = _store()
        store.set_pending(
            sid,
            {
                "action": action,
                "plan_file": payload.get("plan_file"),
                "comments": payload.get("comments"),
            },
        )
        store.set_mode(sid, "agent" if action == "build" else "plan")
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
    return {"ok": True, "session_id": sid, "action": action, "mode": store.get_mode(sid)}


@router.post("/reset")
async def reset(body: dict = Body(default_factory=dict)) -> dict:
    payload = body if isinstance(body, dict) else {}
    sid = _clean_session_id(payload.get("session_id"))
    store = _store()
    if sid:
        store.clear_session(sid)
    return {
        "ok": True,
        "session_id": sid,
        "mode": store.get_mode(sid) if sid else store.get_default(),
    }
