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


_DEFAULT_INJECT = {
    "aspect_ratio": "Aspect ratio must be {label}.",
    "size": "Target resolution approximately {value} pixels (width x height).",
    "quality": "Image quality: {value}.",
    "n": "Generate exactly {value} image(s).",
    "background": "Background must be {value}.",
}
_SLOTS = ("aspect_ratio", "size", "quality", "n", "background")
_DEFAULT_KEYS = {
    "aspect_ratio": "aspect_ratio",
    "size": "size",
    "quality": "quality",
    "n": "n",
    "background": "background",
}


def _as_option(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        return {"label": text, "value": text, "enabled": True}
    if not isinstance(raw, dict):
        return None
    value = str(raw.get("value") if raw.get("value") is not None else raw.get("label") or "").strip()
    label = str(raw.get("label") if raw.get("label") is not None else value).strip() or value
    if not value:
        return None
    return {"label": label, "value": value, "enabled": bool(raw.get("enabled", True))}


def _field_from(slot: str, raw: Any) -> Dict[str, Any]:
    key = _DEFAULT_KEYS[slot]
    options: List[Dict[str, Any]] = []
    if isinstance(raw, dict):
        custom = str(raw.get("key") or "").strip()
        if custom:
            key = custom
        for item in raw.get("options") or []:
            opt = _as_option(item)
            if opt:
                options.append(opt)
    if isinstance(raw, dict) and "inject" in raw:
        inject = str(raw.get("inject") if raw.get("inject") is not None else "")
    else:
        inject = _DEFAULT_INJECT[slot]
    return {"key": key, "options": options, "inject": inject}


def _legacy_options(values: List[str]) -> List[Dict[str, Any]]:
    return [{"label": value, "value": value, "enabled": True} for value in values]


def normalize_model(raw: Dict[str, Any]) -> Dict[str, Any]:
    incoming = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    fields = {slot: _field_from(slot, incoming.get(slot)) for slot in _SLOTS}
    if not any(fields[slot]["options"] for slot in _SLOTS):
        ratios = _clean_ratios(raw.get("aspect_ratios"))
        qualities = _clean_qualities(raw.get("qualities"))
        if "qualities" not in raw and raw.get("quality") is True:
            qualities = list(QUALITY_PRESETS)
        counts = _clean_counts(raw.get("counts"))
        if ratios:
            fields["aspect_ratio"]["options"] = _legacy_options(ratios)
        if qualities:
            fields["quality"]["options"] = _legacy_options(qualities)
        if counts:
            fields["n"]["options"] = _legacy_options(counts)
        if raw.get("transparent"):
            fields["background"]["options"] = _legacy_options(["opaque", "transparent"])
    return {
        "id": str(raw.get("id") or "").strip(),
        "enabled": bool(raw.get("enabled")),
        "ratio_controls_size": bool(raw.get("ratio_controls_size")),
        "fields": fields,
    }


def _enabled_options(field: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [opt for opt in field.get("options") or [] if opt.get("enabled") and str(opt.get("value") or "").strip()]


def assert_model(model: Dict[str, Any]) -> None:
    if not model.get("ratio_controls_size"):
        return
    ratios = _enabled_options(model["fields"]["aspect_ratio"])
    sizes = _enabled_options(model["fields"]["size"])
    if len(ratios) != len(sizes):
        raise ValueError("aspect_ratio and size enabled option counts must match")


def _public_model(raw: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_model(raw)


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
        model = normalize_model({**raw, "id": model_id, "enabled": bool(raw.get("enabled"))})
        assert_model(model)
        cleaned.append(model)
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


def _enum_param(options: List[Dict[str, Any]], *, display: Optional[str] = None) -> Dict[str, Any]:
    enum = []
    for opt in options:
        item = {"value": opt["value"], "label": opt["label"]}
        if opt.get("inject_label"):
            item["inject_label"] = opt["inject_label"]
        enum.append(item)
    spec: Dict[str, Any] = {
        "type": "enum",
        "enum": enum,
        "default": enum[0]["value"],
        "ui": "select",
    }
    if display:
        spec["display"] = display
    return spec


def _with_inject(spec: Dict[str, Any], *templates: Any) -> Dict[str, Any]:
    spec["inject_mode"] = "template"
    spec["injects"] = [str(item) for item in templates if str(item or "").strip()]
    return spec


def params_for(model: Dict[str, Any]) -> Dict[str, Any]:
    normalized = model if isinstance(model.get("fields"), dict) else normalize_model(model)
    fields = normalized["fields"]
    params: Dict[str, Any] = {"prompt": {"type": "text", "required": True}}
    linked = bool(normalized.get("ratio_controls_size"))
    if linked:
        ratios = _enabled_options(fields["aspect_ratio"])
        sizes = _enabled_options(fields["size"])
        count = min(len(ratios), len(sizes))
        if count:
            wire = str(fields["size"].get("key") or "size")
            params[wire] = _with_inject(
                _enum_param([
                    {
                        "value": sizes[i]["value"],
                        "label": ratios[i]["label"],
                        "inject_label": sizes[i]["label"],
                    }
                    for i in range(count)
                ], display="aspect_ratio"),
                fields["size"].get("inject") if fields["size"].get("inject") is not None else _DEFAULT_INJECT["size"],
            )
    else:
        for slot in ("aspect_ratio", "size"):
            options = _enabled_options(fields[slot])
            if options:
                wire = str(fields[slot].get("key") or _DEFAULT_KEYS[slot])
                params[wire] = _with_inject(
                    _enum_param(options),
                    fields[slot].get("inject") if fields[slot].get("inject") is not None else _DEFAULT_INJECT[slot],
                )
    for slot in ("quality", "n", "background"):
        options = _enabled_options(fields[slot])
        if not options:
            continue
        spec = _enum_param(options)
        if slot == "n":
            spec["type"] = "integer"
        params[str(fields[slot].get("key") or _DEFAULT_KEYS[slot])] = _with_inject(
            spec,
            fields[slot].get("inject") if fields[slot].get("inject") is not None else _DEFAULT_INJECT[slot],
        )
    return params


def render_inject(template: Any, label: str, value: str) -> str:
    return str(template or "").replace("{label}", label).replace("{value}", value).strip()


def _option_for_value(field: Dict[str, Any], sent: str) -> Dict[str, str]:
    for opt in _enabled_options(field):
        if str(opt.get("value") or "") == sent:
            return {"label": str(opt.get("label") or sent), "value": sent}
    return {"label": sent, "value": sent}


def constraint_lines(model: Dict[str, Any], params: Dict[str, Any]) -> Optional[List[str]]:
    """Rendered inject lines for an endpoint model. None when the model has no fields."""
    if not isinstance(model, dict):
        return None
    normalized = model if isinstance(model.get("fields"), dict) else normalize_model(model)
    fields = normalized["fields"]
    lines: List[str] = []
    used = set()

    def template_for(slot: str) -> str:
        raw = fields[slot].get("inject")
        if raw is None:
            return _DEFAULT_INJECT[slot]
        return str(raw)

    if normalized.get("ratio_controls_size"):
        size_field = fields["size"]
        size_key = str(size_field.get("key") or "size")
        sent = str(params.get(size_key) or "").strip()
        if sent:
            sizes = _enabled_options(size_field)
            index = next((i for i, opt in enumerate(sizes) if str(opt.get("value") or "") == sent), 0)
            size_opt = sizes[index] if index < len(sizes) else {"label": sent, "value": sent}
            label = str(size_opt.get("label") or "")
            value = str(size_opt.get("value") or sent)
            line = render_inject(template_for("size"), label, value)
            if line:
                lines.append(line)
            used.update(("aspect_ratio", "size"))
    for slot in _SLOTS:
        if slot in used:
            continue
        field = fields[slot]
        key = str(field.get("key") or _DEFAULT_KEYS[slot])
        sent = str(params.get(key) or "").strip()
        if not sent:
            continue
        opt = _option_for_value(field, sent)
        line = render_inject(template_for(slot), opt["label"], opt["value"])
        if line:
            lines.append(line)
    return lines


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
