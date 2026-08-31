"""REST API for the create-image Desktop panel.

Panel does not call the image backend for chat itself. It:
  - lists configured image_gen provider+model options
  - reports selected model capabilities / params
  - stores param + route overrides that ``image_generate`` merges
  - previews prompt_constraints injection text
  - on composer send while open, writes a one-shot ``direct`` flag so the
    agent turn skips the main model and runs ``image_generate`` immediately
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from overrides import (  # noqa: E402
    active_params_for_tool,
    clear_overrides,
    read_overrides,
    write_overrides,
)

_SIZE_RATIO_HINTS = {
    "1254x1254": "1:1",
    "1086x1448": "3:4",
    "941x1672": "9:16",
    "1448x1086": "4:3",
    "1672x941": "16:9",
    "1024x1024": "1:1",
    "1024x1536": "2:3",
    "1536x1024": "3:2",
    "1024x1365": "3:4",
    "1365x1024": "4:3",
    "1088x1920": "9:16",
    "1920x1088": "16:9",
    "2048x2048": "1:1",
    "2560x1440": "16:9",
    "1440x2560": "9:16",
    "3840x2160": "16:9",
    "2160x3840": "9:16",
}

_META_KEYS = frozenset(
    {
        "provider",
        "model",
        "use_gateway",
        "api_key",
        "base_url",
        "api",
        "key_env",
        "enabled",
    }
)


class OverridesBody(BaseModel):
    active: bool = True
    session_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    size: Optional[str] = None
    quality: Optional[str] = None
    n: Optional[int] = None
    background: Optional[str] = None
    output_format: Optional[str] = None
    output_compression: Optional[int] = None
    moderation: Optional[str] = None
    aspect_ratio: Optional[str] = None
    prompt_constraints: Optional[bool] = None
    direct: Optional[bool] = None
    prompt: Optional[str] = None
    image_url: Optional[str] = None
    reference_image_urls: Optional[List[str]] = None


class PreviewBody(BaseModel):
    prompt: str = ""
    size: Optional[str] = None
    quality: Optional[str] = None
    n: Optional[int] = None
    background: Optional[str] = None
    output_format: Optional[str] = None
    moderation: Optional[str] = None
    aspect_ratio: Optional[str] = None
    prompt_constraints: bool = True
    is_edit: bool = False


def _load_image_gen() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception:
        return {}


def _config_default_route() -> Tuple[str, str]:
    section = _load_image_gen()
    provider = str(section.get("provider") or "").strip()
    model = str(section.get("model") or "").strip()
    return provider, model


def _yaml_model_block(provider_name: str, model: str) -> Dict[str, Any]:
    section = _load_image_gen()
    prov = section.get(provider_name) if provider_name else None
    if not isinstance(prov, dict):
        return {}
    models = prov.get("models")
    if not isinstance(models, dict):
        return {}
    block = models.get(model)
    return dict(block) if isinstance(block, dict) else {}


def _named_provider_keys() -> set:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        providers = cfg.get("providers") if isinstance(cfg, dict) else None
        if not isinstance(providers, dict):
            return set()
        return {str(k).strip() for k in providers.keys() if str(k).strip()}
    except Exception:
        return set()


def _catalog_item(
    provider_name: str,
    model_id: str,
    *,
    display: str = "",
    prompt_constraints: bool = False,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    shown = (display or model_id).strip() or model_id
    return {
        "id": f"{provider_name}::{model_id}",
        "provider": provider_name,
        "model": model_id,
        "display": shown,
        "label": shown,
        "prompt_constraints": bool(prompt_constraints),
        "params": params if isinstance(params, dict) else {},
    }


def _catalog() -> List[Dict[str, Any]]:
    """Provider+model pairs: bundled plugin caps, yaml overlay if present.

    A backend is listed when it is the active ``image_gen.provider``, has a
    ``providers.<name>`` block, or still has ``image_gen.<name>.models`` in yaml.
    """
    section = _load_image_gen()
    named = _named_provider_keys()
    active = str(section.get("provider") or "").strip()
    by_id: Dict[str, Dict[str, Any]] = {}

    def _want(provider_name: str) -> bool:
        return (
            provider_name == active
            or provider_name in named
            or (
                isinstance(section.get(provider_name), dict)
                and isinstance(section[provider_name].get("models"), dict)
                and bool(section[provider_name]["models"])
            )
        )

    try:
        from hermes_cli.plugins import _ensure_plugins_discovered
        from agent.image_gen_registry import list_providers

        _ensure_plugins_discovered()
        for provider in list_providers():
            provider_name = str(getattr(provider, "name", "") or "").strip()
            if not provider_name or not _want(provider_name):
                continue
            models = []
            if hasattr(provider, "list_models"):
                try:
                    models = provider.list_models() or []
                except Exception as exc:
                    logger.debug("list_models(%s) failed: %s", provider_name, exc)
            for raw in models:
                if not isinstance(raw, dict):
                    continue
                model_id = str(raw.get("id") or "").strip()
                if not model_id:
                    continue
                caps = raw
                if hasattr(provider, "model_capabilities"):
                    try:
                        live = provider.model_capabilities(model_id)
                        if isinstance(live, dict) and live:
                            caps = {**raw, **live}
                    except Exception:
                        pass
                item = _catalog_item(
                    provider_name,
                    model_id,
                    display=str(caps.get("display") or model_id),
                    prompt_constraints=bool(caps.get("prompt_constraints")),
                    params=caps.get("params") if isinstance(caps.get("params"), dict) else {},
                )
                by_id[item["id"]] = item
    except Exception as exc:
        logger.debug("catalog providers failed: %s", exc)

    for key, val in section.items():
        if key in _META_KEYS or not isinstance(val, dict):
            continue
        models = val.get("models")
        if not isinstance(models, dict) or not models:
            continue
        provider_name = str(key).strip()
        if not provider_name:
            continue
        for mid, block in models.items():
            model_id = str(mid).strip()
            if not model_id:
                continue
            b = block if isinstance(block, dict) else {}
            rid = f"{provider_name}::{model_id}"
            prev = by_id.get(rid, {})
            display = str(b.get("display") or prev.get("display") or model_id).strip() or model_id
            params = b.get("params") if isinstance(b.get("params"), dict) else prev.get("params")
            by_id[rid] = _catalog_item(
                provider_name,
                model_id,
                display=display,
                prompt_constraints=(
                    bool(b.get("prompt_constraints"))
                    if "prompt_constraints" in b
                    else bool(prev.get("prompt_constraints"))
                ),
                params=params,
            )

    items = list(by_id.values())
    items.sort(key=lambda x: (x["provider"], x["model"]))
    return items


def _resolve_route(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[str, str]:
    """Priority: explicit args → panel overrides → config top-level."""
    ov = read_overrides()
    p = (provider or "").strip() or None
    m = (model or "").strip() or None
    if ov.get("active"):
        if not p:
            p = ov.get("provider") or None
        if not m:
            m = ov.get("model") or None
    cfg_p, cfg_m = _config_default_route()
    p = p or cfg_p
    m = m or cfg_m
    # If model missing, first model of provider in catalog.
    if p and not m:
        for it in _catalog():
            if it["provider"] == p:
                m = it["model"]
                break
    return p or "", m or ""


def _get_provider(provider_name: str):
    if not provider_name:
        return None
    try:
        from hermes_cli.plugins import _ensure_plugins_discovered
        from agent.image_gen_registry import get_provider

        _ensure_plugins_discovered()
        provider = get_provider(provider_name)
        if provider is None:
            _ensure_plugins_discovered(force=True)
            provider = get_provider(provider_name)
        return provider
    except Exception as exc:
        logger.debug("get_provider(%s) failed: %s", provider_name, exc)
        return None


def _caps_from_yaml(provider_name: str, model: str) -> Dict[str, Any]:
    block = _yaml_model_block(provider_name, model)
    params = block.get("params") if isinstance(block.get("params"), dict) else {}
    if not params:
        params = {"prompt": {"type": "text", "required": True}}
    elif "prompt" not in params:
        params = {"prompt": {"type": "text", "required": True}, **params}
    return {
        "id": model or "",
        "provider": provider_name or "",
        "display": str(block.get("display") or model or ""),
        "params": params,
        "prompt_constraints": bool(block.get("prompt_constraints")),
        "source": "config.yaml",
    }


def _caps(provider, provider_name: str, model: str) -> Dict[str, Any]:
    # Prefer live provider caps, but always fall back to yaml so the panel
    # still shows configured params when the plugin isn't loaded yet.
    yaml_caps = _caps_from_yaml(provider_name, model)
    if provider is None:
        return yaml_caps
    live: Dict[str, Any] = {}
    if hasattr(provider, "model_capabilities"):
        try:
            caps = provider.model_capabilities(model or None)
            if isinstance(caps, dict):
                live = caps
        except Exception as exc:
            logger.debug("model_capabilities failed: %s", exc)
    if not live:
        try:
            base = provider.capabilities() or {}
        except Exception:
            base = {}
        if isinstance(base.get("model_capabilities"), dict):
            live = base["model_capabilities"]
        else:
            live = {
                "id": model or base.get("model") or "",
                "provider": getattr(provider, "name", provider_name),
                "display": model,
                "params": base.get("model_params") or {},
            }
    # Merge: yaml params fill gaps / win when live params empty.
    live_params = live.get("params") if isinstance(live.get("params"), dict) else {}
    yaml_params = yaml_caps.get("params") if isinstance(yaml_caps.get("params"), dict) else {}
    # Drop prompt-only stubs when yaml has real knobs.
    live_keys = {k for k in live_params.keys() if k != "prompt"}
    if not live_keys and yaml_params:
        params = yaml_params
        source = "config.yaml"
    else:
        params = {**yaml_params, **live_params} if yaml_params else live_params
        if "prompt" not in params:
            params = {"prompt": {"type": "text", "required": True}, **params}
        source = "provider+config"
    out = {
        **yaml_caps,
        **live,
        "id": model or live.get("id") or "",
        "provider": provider_name or live.get("provider") or "",
        "display": live.get("display") or yaml_caps.get("display") or model,
        "params": params,
        "source": source,
    }
    return out


def _model_prompt_constraints(provider_name: str, model: str) -> bool:
    block = _yaml_model_block(provider_name, model)
    if block and "prompt_constraints" in block:
        return bool(block.get("prompt_constraints"))
    provider = _get_provider(provider_name)
    if provider is not None and hasattr(provider, "model_capabilities"):
        try:
            caps = provider.model_capabilities(model)
            if isinstance(caps, dict):
                return bool(caps.get("prompt_constraints"))
        except Exception:
            pass
    return False


def _persist_image_gen_route(provider: str, model: str) -> Dict[str, Any]:
    """Write top-level image_gen.provider + image_gen.model into config.yaml.

    Only updates those two keys; leaves models/params blocks untouched.
    """
    p = (provider or "").strip()
    m = (model or "").strip()
    if not p or not m:
        return {"provider": p, "model": m, "saved": False}
    # Validate against catalog so we never persist junk ids.
    valid = {(it["provider"], it["model"]) for it in _catalog()}
    if (p, m) not in valid:
        logger.warning("refuse config route persist: unknown %s / %s", p, m)
        return {"provider": p, "model": m, "saved": False, "error": "unknown_route"}
    try:
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        if not isinstance(cfg, dict):
            cfg = {}
        ig = cfg.get("image_gen")
        if not isinstance(ig, dict):
            ig = {}
            cfg["image_gen"] = ig
        prev_p = str(ig.get("provider") or "").strip()
        prev_m = str(ig.get("model") or "").strip()
        if prev_p == p and prev_m == m:
            return {"provider": p, "model": m, "saved": False, "unchanged": True}
        ig["provider"] = p
        ig["model"] = m
        save_config(
            cfg,
            preserve_keys={("image_gen", "provider"), ("image_gen", "model")},
        )
        return {"provider": p, "model": m, "saved": True, "previous": {"provider": prev_p, "model": prev_m}}
    except Exception as exc:
        logger.exception("persist image_gen route failed")
        return {"provider": p, "model": m, "saved": False, "error": str(exc)}


def augment_prompt_with_output_constraints(
    prompt: str,
    extra_params: Optional[Dict[str, Any]] = None,
    *,
    is_edit: bool = False,
) -> str:
    text = (prompt or "").strip()
    if not text:
        return text
    params = extra_params if isinstance(extra_params, dict) else {}
    lines: list[str] = []

    size = params.get("size")
    if isinstance(size, str) and size.strip():
        size_s = size.strip()
        if size_s.lower() != "auto":
            ratio = _SIZE_RATIO_HINTS.get(size_s)
            if not ratio and "x" in size_s.lower():
                try:
                    w_s, h_s = size_s.lower().split("x", 1)
                    w, h = int(w_s), int(h_s)
                    if w > 0 and h > 0:
                        g = math.gcd(w, h)
                        ratio = f"{w // g}:{h // g}"
                except Exception:
                    ratio = None
            if ratio:
                lines.append(
                    f"Aspect ratio must be {ratio}. "
                    f"Target resolution approximately {size_s} pixels (width x height)."
                )
            else:
                lines.append(
                    f"Target resolution approximately {size_s} pixels (width x height)."
                )

    ar = params.get("aspect_ratio")
    if (
        isinstance(ar, str)
        and ar.strip()
        and ":" in ar
        and not any("Aspect ratio" in x for x in lines)
    ):
        lines.append(f"Aspect ratio must be {ar.strip()}.")

    quality = params.get("quality")
    if isinstance(quality, str) and quality.strip():
        q = quality.strip().lower()
        if q == "auto":
            lines.append(
                "Image quality: auto (choose appropriate detail automatically)."
            )
        elif q == "low":
            lines.append("Image quality: low (faster, less fine detail).")
        elif q == "medium":
            lines.append("Image quality: medium.")
        elif q == "high":
            lines.append("Image quality: high (maximum detail and sharpness).")
        else:
            lines.append(f"Image quality: {q}.")

    n_raw = params.get("n")
    if n_raw is not None and n_raw != "":
        try:
            n_i = int(n_raw)
        except (TypeError, ValueError):
            n_i = 0
        if n_i == 1:
            lines.append("Generate exactly 1 image.")
        elif n_i > 1:
            lines.append(f"Generate exactly {n_i} distinct image variations.")

    bg = params.get("background")
    if isinstance(bg, str):
        bg_l = bg.strip().lower()
        if bg_l == "transparent":
            lines.append(
                "Background must be fully transparent with a real alpha channel. "
                "Do not paint any solid color backdrop."
            )
        elif bg_l == "opaque":
            lines.append("Background must be fully opaque with no transparency.")

    fmt = params.get("output_format")
    if isinstance(fmt, str) and fmt.strip():
        lines.append(f"Deliver the final image as {fmt.strip().upper()} format.")

    mod = params.get("moderation")
    if isinstance(mod, str) and mod.strip().lower() == "low":
        lines.append(
            "Apply a low/lenient safety filter; allow broader creative content within policy."
        )

    if is_edit:
        lines.append(
            "This is an edit of the provided source image(s). Preserve identity, "
            "composition, and details that are not explicitly changed by the user request."
        )

    if not lines:
        return text

    marker = "[Output constraints]"
    if marker in text:
        return text
    block = marker + "\n" + "\n".join(f"- {line}" for line in lines)
    return f"{text}\n\n{block}"


@router.get("/catalog")
async def catalog():
    cfg_p, cfg_m = _config_default_route()
    items = _catalog()
    return {
        "options": items,
        "default_provider": cfg_p,
        "default_model": cfg_m,
        "default_id": f"{cfg_p}::{cfg_m}" if cfg_p and cfg_m else "",
    }


@router.get("/capabilities")
async def capabilities(
    provider: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
):
    provider_name, model_id = _resolve_route(provider, model)
    plugin = _get_provider(provider_name)
    caps = _caps(plugin, provider_name, model_id)
    available = plugin is not None and bool(
        getattr(plugin, "is_available", lambda: True)()
    )
    # Params from yaml still count as ready for UI.
    params = caps.get("params") if isinstance(caps, dict) else {}
    has_ui_params = isinstance(params, dict) and any(k != "prompt" for k in params)
    ready = available or has_ui_params

    overrides = read_overrides()
    cfg_pc = _model_prompt_constraints(provider_name, model_id)
    panel_pc = overrides.get("prompt_constraints")
    # When user already selected this route, honor panel toggle; else config default.
    same_route = (
        overrides.get("active")
        and (overrides.get("provider") or provider_name) == provider_name
        and (overrides.get("model") or model_id) == model_id
    )
    if same_route and isinstance(panel_pc, bool):
        effective_pc = panel_pc
    else:
        effective_pc = cfg_pc

    if isinstance(caps, dict):
        caps = {**caps, "prompt_constraints": effective_pc}

    return {
        "provider": provider_name,
        "model": model_id,
        "id": f"{provider_name}::{model_id}" if provider_name and model_id else "",
        "available": available,
        "ready": ready,
        "capabilities": caps,
        "overrides": overrides,
        "prompt_constraints": effective_pc,
        "prompt_constraints_default": cfg_pc,
        "catalog": _catalog(),
        "default_provider": _config_default_route()[0],
        "default_model": _config_default_route()[1],
    }


@router.get("/overrides")
async def get_overrides():
    return read_overrides()


@router.put("/overrides")
async def put_overrides(body: OverridesBody):
    params = {
        "size": body.size,
        "quality": body.quality,
        "n": body.n,
        "background": body.background,
        "output_format": body.output_format,
        "output_compression": body.output_compression,
        "moderation": body.moderation,
        "aspect_ratio": body.aspect_ratio,
    }
    if not body.active:
        return clear_overrides()
    state = write_overrides(
        active=True,
        params=params,
        session_id=body.session_id,
        prompt_constraints=body.prompt_constraints,
        provider=body.provider,
        model=body.model,
        direct=body.direct,
        prompt=body.prompt,
        image_url=body.image_url,
        reference_image_urls=body.reference_image_urls,
    )
    # Sync config.yaml top-level selection whenever panel sets a route.
    config_saved = None
    if body.provider and body.model:
        config_saved = _persist_image_gen_route(body.provider, body.model)
    return {**state, "config": config_saved}


@router.delete("/overrides")
async def delete_overrides():
    return clear_overrides()


@router.post("/preview-prompt")
async def preview_prompt(body: PreviewBody):
    params = {
        "size": body.size,
        "quality": body.quality,
        "n": body.n,
        "background": body.background,
        "output_format": body.output_format,
        "moderation": body.moderation,
        "aspect_ratio": body.aspect_ratio,
    }
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    base = (body.prompt or "").strip() or "(your prompt)"
    if body.prompt_constraints:
        final = augment_prompt_with_output_constraints(
            base, clean, is_edit=bool(body.is_edit)
        )
    else:
        final = base
    return {
        "prompt": base,
        "final_prompt": final,
        "injected": bool(body.prompt_constraints) and final != base,
        "params": clean,
    }


class GenerateBody(BaseModel):
    prompt: str = Field(..., min_length=1)
    provider: Optional[str] = None
    model: Optional[str] = None
    size: Optional[str] = None
    quality: Optional[str] = None
    n: Optional[int] = None
    background: Optional[str] = None
    output_format: Optional[str] = None
    output_compression: Optional[int] = None
    moderation: Optional[str] = None
    aspect_ratio: Optional[str] = None


@router.post("/generate")
async def generate(body: GenerateBody):
    provider_name, model = _resolve_route(body.provider, body.model)
    provider = _get_provider(provider_name)
    if provider is None:
        raise HTTPException(
            status_code=400,
            detail=f"image_gen provider '{provider_name}' not registered",
        )
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    kwargs: Dict[str, Any] = {"prompt": body.prompt.strip(), "model": model}
    panel = active_params_for_tool(None)
    for key in (
        "size",
        "quality",
        "n",
        "background",
        "output_format",
        "output_compression",
        "moderation",
        "aspect_ratio",
    ):
        if key in panel and panel[key] is not None and panel[key] != "":
            kwargs[key] = panel[key]
        value = getattr(body, key, None)
        if value is not None and value != "":
            kwargs[key] = value

    try:
        result = provider.generate(**kwargs)
    except TypeError:
        result = provider.generate(
            prompt=body.prompt.strip(), aspect_ratio="square", model=model
        )
    except Exception as exc:
        logger.exception("create-image generate failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="provider returned non-dict")
    return result
