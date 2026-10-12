"""User-defined OpenAI-compatible image endpoints for the create-image plugin.

The API key lives in this file only. Public views never include it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROVIDER_NAME = "openai_compat"
ASPECT_PRESETS = ("1:1", "16:9", "9:16", "3:4", "4:3", "2:3", "3:2")
QUALITY_PRESETS = ("low", "medium", "high")
COUNT_PRESETS = ("1", "2", "4", "8")
_RATIO_RE = re.compile(r"^\d{1,4}:\d{1,4}$")
_QUALITY_RE = re.compile(r"^[\w.+-]{1,32}$")
_COUNT_RE = re.compile(r"^[1-9]\d{0,2}$")
_FILENAME = "image_gen_endpoints.json"


def store_path() -> Path:
    try:
        from hermes_cli.config import get_hermes_home

        home = Path(get_hermes_home())
    except Exception:
        home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home / _FILENAME


def _empty() -> Dict[str, Any]:
    return {"endpoints": [], "active": {"endpoint_id": "", "model": ""}}


def load_store() -> Dict[str, Any]:
    path = store_path()
    try:
        if not path.is_file():
            return _empty()
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("read image endpoints failed: %s", exc)
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    endpoints = data.get("endpoints")
    active = data.get("active")
    return {
        "endpoints": endpoints if isinstance(endpoints, list) else [],
        "active": active if isinstance(active, dict) else {"endpoint_id": "", "model": ""},
    }


def save_store(data: Dict[str, Any]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _clean_base(url: str) -> str:
    text = (url or "").strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("base_url must be an http(s) URL")
    return text


def _token_list(raw: Any, pattern: re.Pattern) -> List[str]:
    if isinstance(raw, str):
        parts = re.split(r"[\s,]+", raw.strip())
    elif isinstance(raw, list):
        parts = [str(item).strip() for item in raw]
    else:
        parts = []
    out: List[str] = []
    for part in parts:
        if not part or not pattern.match(part) or part in out:
            continue
        out.append(part)
    return out


def _clean_qualities(raw: Any) -> List[str]:
    return _token_list(raw, _QUALITY_RE)


def _clean_counts(raw: Any) -> List[str]:
    return _token_list(raw, _COUNT_RE)


def _clean_ratios(raw: Any) -> List[str]:
    return _token_list(raw, _RATIO_RE)


def _public_model(raw: Dict[str, Any]) -> Dict[str, Any]:
    qualities = _clean_qualities(raw.get("qualities"))
    if "qualities" not in raw and raw.get("quality") is True:
        qualities = list(QUALITY_PRESETS)
    return {
        "id": str(raw.get("id") or "").strip(),
        "enabled": bool(raw.get("enabled")),
        "aspect_ratios": _clean_ratios(raw.get("aspect_ratios")),
        "qualities": qualities,
        "counts": _clean_counts(raw.get("counts")),
        "transparent": bool(raw.get("transparent")),
    }


def _models_of(endpoint: Dict[str, Any]) -> List[Dict[str, Any]]:
    models = endpoint.get("models")
    return models if isinstance(models, list) else []


def _find(data: Dict[str, Any], endpoint_id: str) -> Optional[Dict[str, Any]]:
    for item in data["endpoints"]:
        if isinstance(item, dict) and str(item.get("id") or "") == endpoint_id:
            return item
    return None


def public_endpoint(endpoint: Dict[str, Any]) -> Dict[str, Any]:
    models = []
    for raw in _models_of(endpoint):
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or "").strip()
        if not model_id:
            continue
        model = _public_model(raw)
        if not model["id"]:
            continue
        models.append(model)
    return {
        "id": str(endpoint.get("id") or ""),
        "name": str(endpoint.get("name") or ""),
        "base_url": str(endpoint.get("base_url") or ""),
        "has_key": bool(str(endpoint.get("api_key") or "").strip()),
        "models": models,
    }


def list_public() -> Dict[str, Any]:
    data = load_store()
    active = data.get("active") if isinstance(data.get("active"), dict) else {}
    return {
        "endpoints": [public_endpoint(item) for item in data["endpoints"] if isinstance(item, dict)],
        "active": {
            "endpoint_id": str(active.get("endpoint_id") or ""),
            "model": str(active.get("model") or ""),
        },
        "aspect_presets": list(ASPECT_PRESETS),
        "quality_presets": list(QUALITY_PRESETS),
        "count_presets": list(COUNT_PRESETS),
    }


def upsert_endpoint(*, name: str, base_url: str, api_key: Optional[str], endpoint_id: Optional[str] = None) -> Dict[str, Any]:
    label = (name or "").strip()
    if not label:
        raise ValueError("name is required")
    base = _clean_base(base_url)
    key = (api_key or "").strip()
    data = load_store()
    existing = _find(data, (endpoint_id or "").strip()) if endpoint_id else None
    if existing is None:
        if not key:
            raise ValueError("api_key is required")
        existing = {
            "id": uuid.uuid4().hex,
            "name": label,
            "base_url": base,
            "api_key": key,
            "models": [],
        }
        data["endpoints"].append(existing)
    else:
        existing["name"] = label
        existing["base_url"] = base
        if key:
            existing["api_key"] = key
        elif not str(existing.get("api_key") or "").strip():
            raise ValueError("api_key is required")
    save_store(data)
    return public_endpoint(existing)


def delete_endpoint(endpoint_id: str) -> None:
    data = load_store()
    data["endpoints"] = [
        item
        for item in data["endpoints"]
        if not (isinstance(item, dict) and str(item.get("id") or "") == endpoint_id)
    ]
    active = data.get("active") if isinstance(data.get("active"), dict) else {}
    if str(active.get("endpoint_id") or "") == endpoint_id:
        data["active"] = {"endpoint_id": "", "model": ""}
    save_store(data)


def _http_session(base_url: str):
    import requests

    session = requests.Session()
    host = (urlparse(base_url).hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        session.trust_env = False
    return session


def discover_models(endpoint_id: str) -> List[str]:
    data = load_store()
    endpoint = _find(data, endpoint_id)
    if endpoint is None:
        raise ValueError("endpoint not found")
    base = str(endpoint.get("base_url") or "").strip().rstrip("/")
    key = str(endpoint.get("api_key") or "").strip()
    if not base or not key:
        raise ValueError("endpoint is incomplete")
    session = _http_session(base)
    try:
        response = session.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
    except Exception as exc:
        raise RuntimeError(f"GET /models failed: {exc}") from exc
    if not response.ok:
        detail = (response.text or "")[:300]
        raise RuntimeError(f"GET /models {response.status_code}: {detail}")
    try:
        body = response.json()
    except Exception as exc:
        raise RuntimeError("GET /models returned non-JSON") from exc
    ids: List[str] = []
    rows = body.get("data") if isinstance(body, dict) else body
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, str) and row.strip():
                model_id = row.strip()
            elif isinstance(row, dict):
                model_id = str(row.get("id") or "").strip()
            else:
                model_id = ""
            if model_id and model_id not in ids:
                ids.append(model_id)
    return ids


def save_models(endpoint_id: str, models: List[Dict[str, Any]]) -> Dict[str, Any]:
    data = load_store()
    endpoint = _find(data, endpoint_id)
    if endpoint is None:
        raise ValueError("endpoint not found")
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for raw in models:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        cleaned.append(_public_model({**raw, "id": model_id, "enabled": bool(raw.get("enabled"))}))
    endpoint["models"] = cleaned
    save_store(data)
    return public_endpoint(endpoint)


def _enabled_pairs(data: Dict[str, Any]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    pairs = []
    for endpoint in data["endpoints"]:
        if not isinstance(endpoint, dict):
            continue
        if not str(endpoint.get("base_url") or "").strip() or not str(endpoint.get("api_key") or "").strip():
            continue
        for model in _models_of(endpoint):
            if isinstance(model, dict) and model.get("enabled") and str(model.get("id") or "").strip():
                pairs.append((endpoint, model))
    return pairs


def resolve_active(data: Optional[Dict[str, Any]] = None) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    data = data if data is not None else load_store()
    pairs = _enabled_pairs(data)
    if not pairs:
        return None
    active = data.get("active") if isinstance(data.get("active"), dict) else {}
    want_ep = str(active.get("endpoint_id") or "")
    want_model = str(active.get("model") or "")
    for endpoint, model in pairs:
        if str(endpoint.get("id") or "") == want_ep and str(model.get("id") or "") == want_model:
            return endpoint, model
    return pairs[0]


def set_active(endpoint_id: str, model: str) -> Dict[str, str]:
    data = load_store()
    endpoint = _find(data, endpoint_id)
    if endpoint is None:
        raise ValueError("endpoint not found")
    match = None
    for item in _models_of(endpoint):
        if isinstance(item, dict) and str(item.get("id") or "") == model and item.get("enabled"):
            match = item
            break
    if match is None:
        raise ValueError("model is not enabled on this endpoint")
    data["active"] = {"endpoint_id": endpoint_id, "model": model}
    save_store(data)
    return {"endpoint_id": endpoint_id, "model": model}


def is_ready() -> bool:
    return resolve_active() is not None


def params_for(model: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {"prompt": {"type": "text", "required": True}}
    ratios = _clean_ratios(model.get("aspect_ratios"))
    if ratios:
        default = "1:1" if "1:1" in ratios else ratios[0]
        params["aspect_ratio"] = {
            "type": "enum",
            "enum": ratios,
            "default": default,
            "ui": "select",
        }
    qualities = _clean_qualities(model.get("qualities"))
    if qualities:
        params["quality"] = {
            "type": "enum",
            "enum": qualities,
            "default": "medium" if "medium" in qualities else qualities[0],
            "ui": "select",
        }
    counts = _clean_counts(model.get("counts"))
    if counts:
        params["n"] = {
            "type": "enum",
            "enum": counts,
            "default": "1" if "1" in counts else counts[0],
            "ui": "select",
        }
    if model.get("transparent"):
        params["background"] = {
            "type": "enum",
            "enum": ["opaque", "transparent"],
            "default": "opaque",
            "ui": "select",
        }
    return params


def catalog_items() -> List[Dict[str, Any]]:
    data = load_store()
    items = []
    for endpoint, model in _enabled_pairs(data):
        endpoint_id = str(endpoint.get("id") or "")
        model_id = str(model.get("id") or "")
        name = str(endpoint.get("name") or endpoint_id)
        display = f"{name} · {model_id}"
        items.append(
            {
                "id": f"{endpoint_id}::{model_id}",
                "provider": PROVIDER_NAME,
                "model": model_id,
                "endpoint_id": endpoint_id,
                "display": display,
                "label": display,
                "prompt_constraints": False,
                "params": params_for(model),
            }
        )
    items.sort(key=lambda row: (row["display"], row["model"]))
    return items


def caps_for(endpoint_id: Optional[str], model_id: str) -> Dict[str, Any]:
    data = load_store()
    chosen = None
    for endpoint, model in _enabled_pairs(data):
        if str(model.get("id") or "") != model_id:
            continue
        if endpoint_id and str(endpoint.get("id") or "") != endpoint_id:
            continue
        chosen = (endpoint, model)
        break
    if chosen is None:
        active = resolve_active(data)
        if active and str(active[1].get("id") or "") == model_id:
            chosen = active
    if chosen is None:
        return {
            "id": model_id,
            "provider": PROVIDER_NAME,
            "display": model_id,
            "params": {"prompt": {"type": "text", "required": True}},
            "prompt_constraints": False,
            "source": "unconfigured",
        }
    endpoint, model = chosen
    name = str(endpoint.get("name") or "")
    model_name = str(model.get("id") or model_id)
    return {
        "id": model_name,
        "provider": PROVIDER_NAME,
        "endpoint_id": str(endpoint.get("id") or ""),
        "display": f"{name} · {model_name}" if name else model_name,
        "params": params_for(model),
        "prompt_constraints": False,
        "source": "endpoints",
    }


def credentials_for(model_id: str, endpoint_id: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
    data = load_store()
    active = resolve_active(data)
    chosen = None
    if active is not None:
        endpoint, model = active
        same_model = not model_id or str(model.get("id") or "") == model_id
        same_endpoint = not endpoint_id or str(endpoint.get("id") or "") == endpoint_id
        if same_model and same_endpoint:
            chosen = active
    if chosen is None:
        for endpoint, model in _enabled_pairs(data):
            if model_id and str(model.get("id") or "") != model_id:
                continue
            if endpoint_id and str(endpoint.get("id") or "") != endpoint_id:
                continue
            chosen = (endpoint, model)
            break
    if chosen is None:
        raise RuntimeError("no configured image endpoint")
    endpoint, model = chosen
    base = str(endpoint.get("base_url") or "").strip().rstrip("/")
    key = str(endpoint.get("api_key") or "").strip()
    if not base or not key:
        raise RuntimeError("endpoint is incomplete")
    return base, key, model
