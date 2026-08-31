"""Active create-image panel overrides for image_generate.

Desktop panel writes here while open. ``image_generate`` merges these params
when dispatching to the upstream provider. File lives under HERMES_HOME so the
tool layer can read it without importing this plugin package.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_FILENAME = "create_image_panel.json"
_ALLOWED = (
    "size",
    "quality",
    "n",
    "background",
    "output_format",
    "output_compression",
    "moderation",
    "aspect_ratio",
)


def overrides_path() -> Path:
    try:
        from hermes_cli.config import get_hermes_home

        home = Path(get_hermes_home())
    except Exception:
        home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home / "cache" / _FILENAME


def _clean_params(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in _ALLOWED:
        if key not in raw:
            continue
        value = raw.get(key)
        if value is None or value == "":
            continue
        if key == "n":
            try:
                n = int(value)
            except (TypeError, ValueError):
                continue
            if n < 1:
                continue
            out[key] = n
            continue
        if key == "output_compression":
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                continue
            continue
        if key == "aspect_ratio" and isinstance(value, str):
            out[key] = value.strip()
            continue
        if isinstance(value, (str, int, float, bool)):
            out[key] = value
    return out


def _clean_prompt_constraints(raw: Any) -> Optional[bool]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
    return None


def _clean_str(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return s or None
    return str(raw).strip() or None


def _clean_ref_urls(raw: Any) -> Optional[list]:
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        s = _clean_str(item)
        if s:
            out.append(s)
    return out or None


def _empty_state() -> Dict[str, Any]:
    return {
        "active": False,
        "params": {},
        "prompt_constraints": None,
        "provider": None,
        "model": None,
        "session_id": None,
        "direct": False,
        "prompt": None,
        "image_url": None,
        "reference_image_urls": None,
    }


def read_overrides() -> Dict[str, Any]:
    path = overrides_path()
    try:
        if not path.is_file():
            return _empty_state()
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("read create-image overrides failed: %s", exc)
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    session_id = data.get("session_id")
    if session_id is not None:
        session_id = str(session_id).strip() or None
    pc = _clean_prompt_constraints(data.get("prompt_constraints"))
    if pc is None and isinstance(data.get("params"), dict):
        pc = _clean_prompt_constraints(data["params"].get("prompt_constraints"))
    return {
        "active": bool(data.get("active")),
        "params": _clean_params(data.get("params")),
        "prompt_constraints": pc,
        "provider": _clean_str(data.get("provider")),
        "model": _clean_str(data.get("model")),
        "session_id": session_id,
        "direct": bool(data.get("direct")),
        "prompt": _clean_str(data.get("prompt")),
        "image_url": _clean_str(data.get("image_url")),
        "reference_image_urls": _clean_ref_urls(data.get("reference_image_urls")),
        "updated_at": data.get("updated_at"),
    }


def write_overrides(
    *,
    active: bool,
    params: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    prompt_constraints: Optional[bool] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    direct: Optional[bool] = None,
    prompt: Optional[str] = None,
    image_url: Optional[str] = None,
    reference_image_urls: Optional[list] = None,
) -> Dict[str, Any]:
    if not active:
        direct_val = False
        prompt_val = None
        image_val = None
        refs_val = None
    elif direct is True:
        direct_val = True
        prompt_val = _clean_str(prompt)
        image_val = _clean_str(image_url)
        refs_val = _clean_ref_urls(reference_image_urls)
    elif direct is False:
        direct_val = False
        prompt_val = None
        image_val = None
        refs_val = None
    else:
        existing = read_overrides()
        if existing.get("direct"):
            direct_val = True
            prompt_val = existing.get("prompt")
            image_val = existing.get("image_url")
            refs_val = existing.get("reference_image_urls")
        else:
            direct_val = False
            prompt_val = None
            image_val = None
            refs_val = None

    payload = {
        "active": bool(active),
        "params": _clean_params(params or {}),
        "prompt_constraints": _clean_prompt_constraints(prompt_constraints),
        "provider": _clean_str(provider),
        "model": _clean_str(model),
        "session_id": (str(session_id).strip() or None) if session_id else None,
        "direct": direct_val,
        "prompt": prompt_val,
        "image_url": image_val,
        "reference_image_urls": refs_val,
        "updated_at": time.time(),
    }
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        prefix="create_image_panel_", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return payload


def clear_overrides() -> Dict[str, Any]:
    return write_overrides(
        active=False,
        params={},
        session_id=None,
        prompt_constraints=None,
        provider=None,
        model=None,
    )


def _scoped_ok(state: Dict[str, Any], task_id: Optional[str]) -> bool:
    if not state.get("active"):
        return False
    scoped = state.get("session_id")
    if not scoped:
        return True
    tid = str(task_id or "").strip()
    if not tid or tid == scoped:
        return True
    if scoped in tid or tid in scoped:
        return True
    return False


def active_params_for_tool(task_id: Optional[str] = None) -> Dict[str, Any]:
    state = read_overrides()
    if not _scoped_ok(state, task_id):
        return {}
    return dict(state.get("params") or {})


def active_prompt_constraints_for_tool(task_id: Optional[str] = None) -> Optional[bool]:
    state = read_overrides()
    if not _scoped_ok(state, task_id):
        return None
    return state.get("prompt_constraints")


def active_route_for_tool(task_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Return (provider, model) selected on the open panel, else (None, None)."""
    state = read_overrides()
    if not _scoped_ok(state, task_id):
        return None, None
    return state.get("provider"), state.get("model")
