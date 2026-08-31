"""Image gen backend routed through the named Hermes provider ``chatgpt2api``."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    normalize_reference_images,
    resolve_aspect_ratio,
    save_b64_image,
    save_url_image,
    success_response,
)
from agent.secret_scope import get_secret

logger = logging.getLogger(__name__)

PROVIDER_NAME = "chatgpt2api"
DEFAULT_MODEL = "gpt-image-2"

_SIZE_RE = re.compile(r"^(\d+)x(\d+)$", re.I)

def _size_presets(*, codex: bool) -> list:
    rows = [
        ("1024x1024", "1:1", "1:1"),
        ("1024x1536", "2:3", "2:3"),
        ("1536x1024", "3:2", "3:2"),
        ("1024x1365", "3:4", "3:4"),
        ("1365x1024", "4:3", "4:3"),
        ("1088x1920", "9:16", "9:16"),
        ("1920x1088", "16:9", "16:9"),
    ]
    if codex:
        rows += [
            ("2048x2048", "1:1", "1:1(2k)"),
            ("2560x1440", "16:9", "16:9(2k)"),
            ("1440x2560", "9:16", "9:16(2k)"),
            ("3840x2160", "16:9", "16:9(4k)"),
            ("2160x3840", "9:16", "9:16(4k)"),
        ]
    out = [
        {"value": v, "ratio": r, "key": lab, "label": lab}
        for v, r, lab in rows
    ]
    out.append({"value": "auto", "ratio": "auto", "key": "auto", "label": "auto"})
    return out


def _default_params(*, codex: bool) -> Dict[str, Any]:
    return {
        "prompt": {"type": "text", "required": True},
        "size": {
            "type": "size",
            "default": "1024x1024",
            "presets": _size_presets(codex=codex),
            "custom": True,
        },
        "background": {
            "type": "enum",
            "enum": ["auto", "transparent", "opaque"],
            "default": "auto",
            "ui": "select",
        },
        "quality": {
            "type": "enum",
            "enum": ["auto", "low", "medium", "high"],
            "default": "auto",
            "ui": "select",
        },
        "n": {
            "type": "enum",
            "enum": [1, 2, 3, 4],
            "default": 1,
            "ui": "select",
        },
        "response_format": {
            "type": "enum",
            "enum": ["b64_json", "url"],
            "default": "b64_json",
            "ui": "hidden",
        },
    }


# Former per-profile ``image_gen.chatgpt2api.models`` (same across profiles).
# Size ``ratio``/``key``/``label`` are the pre-YAML-1.1 strings (``1:1``, not 61).
_MODEL_CAPS: Dict[str, Dict[str, Any]] = {
    "gpt-image-2": {
        "display": "ChatGPT Image2 (Free)",
        "prompt_constraints": False,
        "speed": "~20-90s",
        "strengths": "ChatGPT web picture path via chatgpt2api (Free-capable; 1k sizes)",
        "params": _default_params(codex=False),
    },
    "codex-gpt-image-2": {
        "display": "ChatGPT Image2 (Paid)",
        "prompt_constraints": False,
        "speed": "~20-90s",
        "strengths": "Codex image path via chatgpt2api (Plus/Team/Pro; 1k/2k/4k)",
        "params": _default_params(codex=True),
    },
}


def _load_image_gen_section() -> Dict[str, Any]:
    from hermes_cli.config import load_config

    cfg = load_config()
    section = cfg.get("image_gen") if isinstance(cfg, dict) else None
    return section if isinstance(section, dict) else {}


def _load_named_provider() -> Dict[str, Any]:
    from hermes_cli.config import load_config

    cfg = load_config()
    providers = cfg.get("providers") if isinstance(cfg, dict) else None
    if not isinstance(providers, dict):
        return {}
    block = providers.get(PROVIDER_NAME)
    return block if isinstance(block, dict) else {}


def _resolve_endpoint() -> Tuple[str, str]:
    block = _load_named_provider()
    base = str(block.get("api") or block.get("base_url") or "").strip().rstrip("/")
    key_env = str(block.get("key_env") or "").strip()
    if not base:
        raise RuntimeError(f"providers.{PROVIDER_NAME}.api missing in config.yaml")
    if not key_env:
        raise RuntimeError(f"providers.{PROVIDER_NAME}.key_env missing in config.yaml")
    api_key = (get_secret(key_env) or "").strip()
    if not api_key:
        raise RuntimeError(f"{key_env} is empty")
    return base, api_key


def _known_model_ids() -> set:
    ids = set(_MODEL_CAPS.keys())
    section = _load_image_gen_section()
    nested = section.get(PROVIDER_NAME) if isinstance(section.get(PROVIDER_NAME), dict) else {}
    models = nested.get("models") if isinstance(nested, dict) else None
    if isinstance(models, dict):
        ids.update(str(k) for k in models.keys())
    return ids


def _resolve_model() -> str:
    env_override = os.environ.get("CHATGPT2API_IMAGE_MODEL", "").strip()
    if env_override:
        return env_override

    # Schema: top-level image_gen.model is the selection; provider block only has models.
    section = _load_image_gen_section()
    known = _known_model_ids()
    top = section.get("model")
    if isinstance(top, str) and top.strip() in known:
        return top.strip()

    nested = section.get(PROVIDER_NAME) if isinstance(section.get(PROVIDER_NAME), dict) else {}
    models = nested.get("models") if isinstance(nested, dict) else None
    if isinstance(models, dict) and models:
        if DEFAULT_MODEL in models:
            return DEFAULT_MODEL
        return str(next(iter(models.keys())))

    return DEFAULT_MODEL



def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _config_model_override(model_id: str) -> Dict[str, Any]:
    section = _load_image_gen_section()
    nested = section.get(PROVIDER_NAME) if isinstance(section.get(PROVIDER_NAME), dict) else {}
    models = nested.get("models") if isinstance(nested, dict) else None
    if not isinstance(models, dict):
        return {}
    block = models.get(model_id)
    return block if isinstance(block, dict) else {}


def resolve_model_capabilities(model_id: str) -> Dict[str, Any]:
    """Return capabilities for a model id.

    If ``image_gen.chatgpt2api.models.<id>.params`` is set, that block is the
    only supported param surface (opt-in). Missing keys unsupported / not shown.

    ``prompt_constraints`` is model-level only.
    """
    override = _config_model_override(model_id)
    builtin = _MODEL_CAPS.get(model_id)

    if isinstance(override.get("params"), dict):
        params = override["params"]
        return {
            "id": model_id,
            "provider": PROVIDER_NAME,
            "display": override.get("display") or (builtin or {}).get("display") or model_id,
            "speed": override.get("speed") or (builtin or {}).get("speed"),
            "strengths": override.get("strengths") or (builtin or {}).get("strengths"),
            "params": params,
            "rules": override.get("rules") if isinstance(override.get("rules"), list) else [],
            "defaults": override.get("defaults") if isinstance(override.get("defaults"), dict) else {},
            "prompt_constraints": bool(override.get("prompt_constraints")),
            "source": "config",
        }

    base = builtin or {
        "display": model_id,
        "params": {"prompt": {"type": "text", "required": True}},
    }
    merged = _deep_merge(base, override) if override else dict(base)
    pc = override.get("prompt_constraints") if override else None
    if pc is None:
        pc = merged.get("prompt_constraints")
    return {
        "id": model_id,
        "provider": PROVIDER_NAME,
        "display": merged.get("display") or model_id,
        "speed": merged.get("speed"),
        "strengths": merged.get("strengths"),
        "params": merged.get("params") if isinstance(merged.get("params"), dict) else {},
        "rules": merged.get("rules") if isinstance(merged.get("rules"), list) else [],
        "defaults": merged.get("defaults") if isinstance(merged.get("defaults"), dict) else {},
        "prompt_constraints": bool(pc),
        "source": "builtin" if not override else "merged",
    }


def filter_generate_params(
    model_id: str,
    *,
    aspect_ratio: str,
    kwargs: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    caps = resolve_model_capabilities(model_id)
    declared = caps.get("params") if isinstance(caps.get("params"), dict) else {}
    fields: Dict[str, Any] = {}
    ignored: List[str] = []

    # size
    if "size" in declared:
        size_spec = declared["size"] if isinstance(declared["size"], dict) else {}
        raw_size = kwargs.get("size")
        presets_raw = size_spec.get("presets") or []
        preset_values: List[str] = []
        for item in presets_raw:
            if isinstance(item, str):
                preset_values.append(item)
            elif isinstance(item, dict) and item.get("value") is not None:
                preset_values.append(str(item["value"]))
        default_size = str(
            size_spec.get("default")
            or (preset_values[0] if preset_values else "1024x1024")
        )
        size = default_size
        if isinstance(raw_size, str) and raw_size.strip():
            cand = raw_size.strip()
            if cand in preset_values or cand.lower() == "auto" or _SIZE_RE.match(cand):
                size = cand
            else:
                ignored.append(f"size={cand}")
        fields["size"] = size
    elif kwargs.get("size") not in (None, ""):
        ignored.append("size")

    # quality
    if "quality" in declared:
        qspec = declared["quality"] if isinstance(declared["quality"], dict) else {}
        allowed = [str(x) for x in (qspec.get("enum") or [])]
        default_q = str(qspec.get("default") or (allowed[0] if allowed else "auto"))
        raw_q = kwargs.get("quality")
        if raw_q is None or raw_q == "":
            fields["quality"] = default_q
        else:
            q = str(raw_q).strip().lower()
            if allowed and q not in allowed:
                ignored.append(f"quality={raw_q}")
                fields["quality"] = default_q
            else:
                fields["quality"] = q
    elif kwargs.get("quality") not in (None, ""):
        ignored.append("quality")

    # background (auto / transparent / opaque)
    if "background" in declared:
        bspec = declared["background"] if isinstance(declared["background"], dict) else {}
        allowed_b = [str(x).strip().lower() for x in (bspec.get("enum") or [])]
        default_b = str(
            bspec.get("default") or (allowed_b[0] if allowed_b else "auto")
        ).strip().lower()
        raw_b = kwargs.get("background")
        if raw_b in (None, ""):
            fields["background"] = default_b
        else:
            b = str(raw_b).strip().lower()
            if allowed_b and b not in allowed_b:
                ignored.append(f"background={raw_b}")
                fields["background"] = default_b
            else:
                fields["background"] = b
    elif kwargs.get("background") not in (None, ""):
        ignored.append("background")

    # n
    if "n" in declared:
        nspec = declared["n"] if isinstance(declared["n"], dict) else {}
        allowed_n: List[int] = []
        for x in nspec.get("enum") or [1]:
            try:
                allowed_n.append(int(x))
            except Exception:
                pass
        default_n = int(nspec.get("default") or (allowed_n[0] if allowed_n else 1))
        raw_n = kwargs.get("n")
        if raw_n in (None, ""):
            fields["n"] = default_n
        else:
            try:
                n_val = int(raw_n)
            except Exception:
                ignored.append(f"n={raw_n}")
                n_val = default_n
            if allowed_n and n_val not in allowed_n:
                ignored.append(f"n={raw_n}")
                n_val = default_n
            fields["n"] = n_val
    elif kwargs.get("n") not in (None, ""):
        ignored.append("n")

    # response_format
    if "response_format" in declared:
        rspec = (
            declared["response_format"]
            if isinstance(declared["response_format"], dict)
            else {}
        )
        allowed = [str(x) for x in (rspec.get("enum") or ["b64_json"])]
        default_r = str(rspec.get("default") or allowed[0])
        raw_r = kwargs.get("response_format")
        if raw_r in (None, ""):
            fields["response_format"] = default_r
        else:
            r = str(raw_r).strip()
            fields["response_format"] = r if r in allowed else default_r
    elif kwargs.get("response_format") not in (None, ""):
        ignored.append("response_format")

    return fields, ignored


def _load_image_bytes(ref: str) -> Tuple[bytes, str]:
    ref = ref.strip()
    lower = ref.lower()
    if lower.startswith(("http://", "https://")):
        resp = requests.get(ref, timeout=60)
        resp.raise_for_status()
        name = ref.split("?", 1)[0].rsplit("/", 1)[-1] or "image.png"
        return resp.content, name
    if lower.startswith("data:"):
        import base64

        header, _, b64 = ref.partition(",")
        ext = "png"
        if "image/" in header:
            ext = header.split("image/", 1)[1].split(";", 1)[0] or "png"
        return base64.b64decode(b64), f"image.{ext}"
    from agent.file_safety import raise_if_read_blocked

    raise_if_read_blocked(ref)
    path = Path(ref).expanduser()
    return path.read_bytes(), path.name or "image.png"


def _save_items(data: List[Any], model_id: str) -> List[str]:
    paths: List[str] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json")
        url = item.get("url")
        prefix = f"{PROVIDER_NAME}_{model_id.replace('/', '_')}_{idx}"
        if b64:
            paths.append(str(save_b64_image(str(b64), prefix=prefix, extension="png")))
        elif url:
            try:
                paths.append(str(save_url_image(str(url), prefix=prefix)))
            except Exception:
                paths.append(str(url))
    return paths


class Chatgpt2apiImageGenProvider(ImageGenProvider):
    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "ChatGPT2API"

    def is_available(self) -> bool:
        try:
            _resolve_endpoint()
            return True
        except Exception:
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        # Prefer configured models keys when present, else builtin.
        section = _load_image_gen_section()
        nested = section.get(PROVIDER_NAME) if isinstance(section.get(PROVIDER_NAME), dict) else {}
        configured = nested.get("models") if isinstance(nested, dict) else None
        ids = list(configured.keys()) if isinstance(configured, dict) and configured else list(_MODEL_CAPS.keys())
        out = []
        for mid in ids:
            caps = resolve_model_capabilities(mid)
            out.append(
                {
                    "id": mid,
                    "display": caps.get("display") or mid,
                    "speed": caps.get("speed"),
                    "strengths": caps.get("strengths"),
                    "params": caps.get("params"),
                    "prompt_constraints": bool(caps.get("prompt_constraints")),
                }
            )
        return out

    def default_model(self) -> Optional[str]:
        return _resolve_model()

    def capabilities(self) -> Dict[str, Any]:
        model_id = _resolve_model()
        model_caps = resolve_model_capabilities(model_id)
        return {
            "modalities": ["text", "image"],
            "max_reference_images": 8,
            "model": model_id,
            "model_params": model_caps.get("params") or {},
            "model_capabilities": model_caps,
        }

    def model_capabilities(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return resolve_model_capabilities(model_id or _resolve_model())

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "ChatGPT2API",
            "badge": "custom",
            "tag": "OpenAI-compatible images via providers.chatgpt2api",
            "env_vars": [],
        }

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)
        if not prompt:
            return error_response(
                error="Prompt is required",
                error_type="invalid_input",
                provider=PROVIDER_NAME,
                aspect_ratio=aspect,
            )

        try:
            base_url, api_key = _resolve_endpoint()
        except Exception as exc:
            return error_response(
                error=str(exc),
                error_type="auth_required",
                provider=PROVIDER_NAME,
                aspect_ratio=aspect,
            )

        model_id = str(kwargs.get("model") or _resolve_model()).strip() or DEFAULT_MODEL
        fields, ignored = filter_generate_params(model_id, aspect_ratio=aspect, kwargs=kwargs)

        sources: List[str] = []
        if isinstance(image_url, str) and image_url.strip():
            sources.append(image_url.strip())
        sources.extend(normalize_reference_images(reference_image_urls) or [])
        is_edit = bool(sources)
        modality = "image" if is_edit else "text"
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            if is_edit:
                files = []
                for ref in sources[:8]:
                    data, fname = _load_image_bytes(ref)
                    field = "image" if len(sources) == 1 else "image[]"
                    files.append((field, (fname, data)))
                form: Dict[str, str] = {
                    "model": model_id,
                    "prompt": prompt,
                }
                for key in ("size", "quality", "background", "response_format"):
                    if key in fields:
                        form[key] = str(fields[key])
                if "n" in fields:
                    form["n"] = str(fields["n"])
                response = requests.post(
                    f"{base_url}/images/edits",
                    headers=headers,
                    files=files,
                    data=form,
                    timeout=600,
                )
            else:
                payload: Dict[str, Any] = {
                    "model": model_id,
                    "prompt": prompt,
                    **fields,
                }
                response = requests.post(
                    f"{base_url}/images/generations",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                    timeout=600,
                )
            if not response.ok:
                return error_response(
                    error=f"{PROVIDER_NAME} image API {response.status_code}: {response.text[:400]}",
                    error_type="api_error",
                    provider=PROVIDER_NAME,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            body = response.json()
        except Exception as exc:
            logger.debug("%s image call failed", PROVIDER_NAME, exc_info=True)
            return error_response(
                error=f"{PROVIDER_NAME} image call failed: {exc}",
                error_type=type(exc).__name__,
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or not data:
            return error_response(
                error=f"{PROVIDER_NAME} returned no image data",
                error_type="empty_response",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            paths = _save_items(data, model_id)
        except Exception as exc:
            return error_response(
                error=f"Could not save image: {exc}",
                error_type="io_error",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        if not paths:
            return error_response(
                error=f"{PROVIDER_NAME} response lacked b64_json and url",
                error_type="empty_response",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        extra = {
            "params": fields,
            "base_url": base_url,
            "ignored": ignored,
        }
        if len(paths) > 1:
            extra["images"] = paths

        return success_response(
            image=paths[0],
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider=PROVIDER_NAME,
            modality=modality,
            extra=extra,
        )


def register(ctx) -> None:
    ctx.register_image_gen_provider(Chatgpt2apiImageGenProvider())
