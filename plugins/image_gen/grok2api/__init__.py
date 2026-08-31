"""Image gen backend routed through the named Hermes provider ``grok2api``."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    normalize_reference_images,
    save_b64_image,
    save_url_image,
    success_response,
)
from agent.secret_scope import get_secret

logger = logging.getLogger(__name__)

PROVIDER_NAME = "grok2api"
DEFAULT_MODEL = "Web/grok-imagine-image-2.0"

# User-approved aspect ratios for Web/grok-imagine-image-2.0
_GROK_ASPECTS = ["1:1", "16:9", "9:16", "3:4", "4:3", "2:3", "3:2"]

_LEGACY_ASPECT_MAP = {
    "landscape": "16:9",
    "square": "1:1",
    "portrait": "9:16",
}

_MODEL_CAPS: Dict[str, Dict[str, Any]] = {
    "Web/grok-imagine-image-2.0": {
        "display": "Grok Web Imagine Image 2.0",
        "prompt_constraints": False,
        "speed": "~10-30s",
        "strengths": "Grok Imagine 2.0 via grok2api",
        "params": {
            "prompt": {"type": "text", "required": True},
            "aspect_ratio": {
                "type": "enum",
                "enum": list(_GROK_ASPECTS),
                "default": "1:1",
                "ui": "select",
            },
        },
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
    env_override = os.environ.get("GROK2API_IMAGE_MODEL", "").strip()
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
    base = _MODEL_CAPS.get(model_id)
    if base is None:
        # Unknown id: still expose grok aspect_ratio set
        base = {
            "display": model_id,
            "params": {
                "prompt": {"type": "text", "required": True},
                "aspect_ratio": {
                    "type": "enum",
                    "enum": list(_GROK_ASPECTS),
                    "default": "1:1",
                    "ui": "select",
                },
            },
        }
    merged = _deep_merge(base, _config_model_override(model_id))
    return {
        "id": model_id,
        "provider": PROVIDER_NAME,
        "display": merged.get("display") or model_id,
        "speed": merged.get("speed"),
        "strengths": merged.get("strengths"),
        "params": merged.get("params") if isinstance(merged.get("params"), dict) else {},
        "rules": merged.get("rules") if isinstance(merged.get("rules"), list) else [],
        "defaults": merged.get("defaults") if isinstance(merged.get("defaults"), dict) else {},
    }


def resolve_native_aspect(
    *,
    aspect_ratio_arg: Any,
    kwargs: Dict[str, Any],
    caps: Dict[str, Any],
) -> Tuple[str, List[str]]:
    """Resolve grok native aspect_ratio. Returns (value, ignored)."""
    ignored: List[str] = []
    declared = (caps.get("params") or {}).get("aspect_ratio") or {}
    allowed = [str(x) for x in (declared.get("enum") or _GROK_ASPECTS)]
    default = str(declared.get("default") or "1:1")

    # Prefer explicit native aspect_ratio kwarg
    raw = kwargs.get("aspect_ratio")
    if isinstance(raw, str) and raw.strip():
        val = raw.strip()
        # accept legacy landscape/square/portrait from tool layer
        if val.lower() in _LEGACY_ASPECT_MAP:
            val = _LEGACY_ASPECT_MAP[val.lower()]
        if val in allowed:
            return val, ignored
        ignored.append("aspect_ratio")

    # Tool-layer landscape/square/portrait comes as generate()'s aspect_ratio param
    if isinstance(aspect_ratio_arg, str) and aspect_ratio_arg.strip():
        val = aspect_ratio_arg.strip()
        if val.lower() in _LEGACY_ASPECT_MAP:
            return _LEGACY_ASPECT_MAP[val.lower()], ignored
        if val in allowed:
            return val, ignored

    defaults = caps.get("defaults") or {}
    if isinstance(defaults.get("aspect_ratio"), str) and defaults["aspect_ratio"] in allowed:
        return defaults["aspect_ratio"], ignored
    return default, ignored


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


class Grok2apiImageGenProvider(ImageGenProvider):
    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "Grok2API"

    def is_available(self) -> bool:
        try:
            _resolve_endpoint()
            return True
        except Exception:
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        out = []
        for mid in ("Web/grok-imagine-image-2.0",):
            meta = _MODEL_CAPS.get(mid) or {}
            caps = resolve_model_capabilities(mid)
            out.append(
                {
                    "id": mid,
                    "display": caps.get("display") or meta.get("display") or mid,
                    "speed": meta.get("speed"),
                    "strengths": meta.get("strengths"),
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
            "max_reference_images": 4,
            "model": model_id,
            "model_params": model_caps.get("params") or {},
            "model_capabilities": model_caps,
        }

    def model_capabilities(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        return resolve_model_capabilities(model_id or _resolve_model())

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Grok2API",
            "badge": "local",
            "tag": "Grok Imagine via providers.grok2api",
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
        if not prompt:
            return error_response(
                error="Prompt is required",
                error_type="invalid_input",
                provider=PROVIDER_NAME,
                aspect_ratio="1:1",
            )

        try:
            base_url, api_key = _resolve_endpoint()
        except Exception as exc:
            return error_response(
                error=str(exc),
                error_type="auth_required",
                provider=PROVIDER_NAME,
                aspect_ratio="1:1",
            )

        model_id = str(kwargs.get("model") or _resolve_model()).strip() or DEFAULT_MODEL
        caps = resolve_model_capabilities(model_id)
        native_aspect, ignored = resolve_native_aspect(
            aspect_ratio_arg=aspect_ratio,
            kwargs=kwargs,
            caps=caps,
        )

        # Drop unsupported GPT-style params silently
        for key in ("size", "quality", "n", "background", "output_format", "output_compression", "moderation"):
            if key in kwargs and kwargs[key] not in (None, ""):
                ignored.append(key)

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
                for ref in sources[:4]:
                    data, fname = _load_image_bytes(ref)
                    field = "image" if len(sources) == 1 else "image[]"
                    files.append((field, (fname, data)))
                response = requests.post(
                    f"{base_url}/images/edits",
                    headers=headers,
                    files=files,
                    data={
                        "model": model_id,
                        "prompt": prompt,
                        "aspect_ratio": native_aspect,
                        "n": "1",
                    },
                    timeout=300,
                )
            else:
                payload = {
                    "model": model_id,
                    "prompt": prompt,
                    "aspect_ratio": native_aspect,
                    "n": 1,
                }
                response = requests.post(
                    f"{base_url}/images/generations",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                    timeout=300,
                )
            if not response.ok:
                return error_response(
                    error=f"{PROVIDER_NAME} image API {response.status_code}: {response.text[:400]}",
                    error_type="api_error",
                    provider=PROVIDER_NAME,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=native_aspect,
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
                aspect_ratio=native_aspect,
            )

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or not data:
            return error_response(
                error=f"{PROVIDER_NAME} returned no image data",
                error_type="empty_response",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=native_aspect,
            )
        first = data[0] if isinstance(data[0], dict) else {}
        b64 = first.get("b64_json")
        url = first.get("url")
        if b64:
            try:
                image_ref = str(save_b64_image(b64, prefix=f"{PROVIDER_NAME}_{model_id.replace('/', '_')}"))
            except Exception as exc:
                return error_response(
                    error=f"Could not save image: {exc}",
                    error_type="io_error",
                    provider=PROVIDER_NAME,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=native_aspect,
                )
        elif url:
            try:
                image_ref = str(save_url_image(url, prefix=f"{PROVIDER_NAME}_{model_id.replace('/', '_')}"))
            except Exception:
                image_ref = str(url)
        else:
            return error_response(
                error=f"{PROVIDER_NAME} response lacked b64_json and url",
                error_type="empty_response",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=native_aspect,
            )

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=native_aspect,
            provider=PROVIDER_NAME,
            modality=modality,
            extra={
                "params": {"aspect_ratio": native_aspect, "n": 1},
                "base_url": base_url,
                "ignored": ignored,
            },
        )


def register(ctx) -> None:
    ctx.register_image_gen_provider(Grok2apiImageGenProvider())
