"""prompt-purge backend routes — mounted at /api/plugins/prompt-purge/.

**Profile selection**
    Every mutating/reading route takes an optional ``target`` — the profile the
    operator picked in the plugin UI. It is deliberately *not* named ``profile``:
    the dashboard auth layer inspects ``?profile=`` / ``body.profile`` to enforce
    "a connection may only touch its own profile" and answers 403
    ``profile_scope_mismatch`` otherwise. ``target`` therefore never changes the
    request's connection scope — the plugin edits another profile's files (which
    it is entitled to do, it runs in-process) without disturbing the global
    ``$apiRequestScope`` for every other page.

    When ``target`` is absent the request's own profile is used.

``/preview`` builds a real AIAgent (no model call) and therefore costs a few
seconds; it runs in a worker thread so the gateway event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

CORE_NAME = "prompt_purge_core"


def _load_core():
    mod = sys.modules.get(CORE_NAME)
    if mod is not None:
        return mod
    path = Path(__file__).resolve().parent.parent / "core.py"
    spec = importlib.util.spec_from_file_location(CORE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[CORE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


core = _load_core()
core.patch()

router = APIRouter()


def _prof(target: Any) -> str:
    """目标 profile；非字符串（如直接调用时的 Query 默认值）按未指定处理。"""
    text = target.strip() if isinstance(target, str) else ""
    return text or core.current_profile_name()


class StateBody(BaseModel):
    target: str = ""
    drop: list[str] = Field(default_factory=list)
    templates: list[str] = Field(default_factory=list)


class TemplateBody(BaseModel):
    content: str


class RenameBody(BaseModel):
    to: str


class ApplyBody(BaseModel):
    target: str = ""
    templates: list[str] = Field(default_factory=list)
    drop: list[str] = Field(default_factory=list)


class PreviewBody(BaseModel):
    target: str = ""
    templates: list[str] = Field(default_factory=list)
    drop: list[str] = Field(default_factory=list)


# ── profile / sections ────────────────────────────────────────────────────
@router.get("/profiles")
def get_profiles() -> dict[str, Any]:
    return {"profiles": core.list_profiles(), "current": core.current_profile_name()}


@router.get("/sections")
async def get_sections(target: str = Query("")) -> dict[str, Any]:
    """Every prompt section seen so far, for ``target`` (default: request's own).

    冷启动（进程刚起、还没有任何会话构建过 prompt）时自动构造一次 agent 把段枚举出来
    —— 纯本地字符串拼接，不发 LLM 请求、不消耗 token，约 4-5 秒。
    """
    prof = _prof(target)
    data = core.sections(prof)
    warmed = False
    if not data:
        try:
            await asyncio.to_thread(core.warm, prof)
            warmed = True
            data = core.sections(prof)
        except Exception:
            pass
    return {"sections": data, "patched": core._APPLIED, "warmed": warmed, "profile": prof}


@router.get("/state")
def get_state(target: str = Query("")) -> dict[str, Any]:
    return core.load_state(_prof(target))


@router.post("/state")
def post_state(body: StateBody) -> dict[str, Any]:
    return core.save_state(_prof(body.target), body.drop, body.templates)


# ── templates ─────────────────────────────────────────────────────────────
@router.get("/templates")
def get_templates() -> dict[str, Any]:
    return {"templates": core.list_templates()}


@router.get("/templates/{name}")
def get_template(name: str) -> dict[str, Any]:
    try:
        return {"name": name, "content": core.read_template(name)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"template not found: {name}")


@router.put("/templates/{name}")
def put_template(name: str, body: TemplateBody) -> dict[str, Any]:
    try:
        core.write_template(name, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "name": name, "chars": len(body.content)}


@router.delete("/templates/{name}")
def delete_template(name: str) -> dict[str, Any]:
    if not core.delete_template(name):
        raise HTTPException(status_code=404, detail=f"template not found: {name}")
    return {"ok": True, "deleted": name}


@router.post("/templates/{name}/rename")
def rename_template(name: str, body: RenameBody) -> dict[str, Any]:
    if not core.rename_template(name, body.to):
        raise HTTPException(status_code=400, detail="rename failed (source missing or target empty)")
    return {"ok": True, "from": name, "to": body.to}


class OpenBody(BaseModel):
    name: str


@router.post("/open")
def open_template(body: OpenBody) -> dict[str, Any]:
    """在 VS Code（或系统默认程序）里打开模板文件。"""
    try:
        return core.open_in_editor(body.name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"template not found: {body.name}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── apply / revert ────────────────────────────────────────────────────────
@router.post("/apply")
def apply(body: ApplyBody) -> dict[str, Any]:
    """Compose the selected templates and write them to ``target``'s SOUL.md."""
    prof = _prof(body.target)
    try:
        core.save_state(prof, body.drop, body.templates)
        result = core.apply_to_soul(prof, body.templates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"write failed: {exc}")
    return {**result, "drop": body.drop, "templates": body.templates}


@router.post("/revert")
def revert(body: ApplyBody) -> dict[str, Any]:
    try:
        return core.revert_soul(_prof(body.target))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="no SOUL.md backup to restore")


# ── preview ───────────────────────────────────────────────────────────────
@router.post("/preview")
async def preview(body: PreviewBody) -> dict[str, Any]:
    """Build the exact system prompt ``target``'s next session would send."""
    try:
        return await asyncio.to_thread(
            core.preview, _prof(body.target), body.templates, body.drop
        )
    except Exception as exc:  # surface the real reason to the UI
        raise HTTPException(status_code=500, detail=f"preview failed: {exc}")
