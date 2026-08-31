"""Create-image plugin: slash command + dashboard REST for Desktop panel."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _active_provider_and_model():
    from hermes_cli.config import load_config
    from hermes_cli.plugins import _ensure_plugins_discovered
    from agent.image_gen_registry import get_provider

    cfg = load_config() if callable(load_config) else {}
    section = cfg.get("image_gen") if isinstance(cfg, dict) else {}
    if not isinstance(section, dict):
        section = {}
    provider_name = str(section.get("provider") or "").strip()
    model = str(section.get("model") or "").strip()
    if provider_name and isinstance(section.get(provider_name), dict):
        nested = section[provider_name].get("model")
        if isinstance(nested, str) and nested.strip():
            model = nested.strip()

    _ensure_plugins_discovered()
    provider = get_provider(provider_name) if provider_name else None
    if provider is not None and not model:
        try:
            model = provider.default_model() or ""
        except Exception:
            model = ""
    return provider_name, model, provider


def _model_capabilities(provider, model: str) -> Dict[str, Any]:
    if provider is None:
        return {
            "id": model or "",
            "provider": "",
            "params": {"prompt": {"type": "text", "required": True}},
        }
    if hasattr(provider, "model_capabilities"):
        try:
            caps = provider.model_capabilities(model or None)
            if isinstance(caps, dict):
                return caps
        except Exception as exc:
            logger.debug("model_capabilities failed: %s", exc)
    try:
        caps = provider.capabilities() or {}
    except Exception:
        caps = {}
    if isinstance(caps.get("model_capabilities"), dict):
        return caps["model_capabilities"]
    return {
        "id": model or caps.get("model") or "",
        "provider": getattr(provider, "name", ""),
        "display": model,
        "params": caps.get("model_params") or {"prompt": {"type": "text", "required": True}},
    }


def _handle_create_image(raw_args: str) -> str:
    """CLI/gateway slash: /create-image [prompt…]

    Without args: show current model capabilities.
    With args: generate immediately using defaults + prompt text.
    """
    provider_name, model, provider = _active_provider_and_model()
    caps = _model_capabilities(provider, model)
    prompt = (raw_args or "").strip()
    if not prompt:
        params = caps.get("params") or {}
        keys = ", ".join(sorted(params.keys())) or "(prompt only)"
        return (
            f"Create Image\n"
            f"provider: {provider_name or '(none)'}\n"
            f"model: {model or '(none)'}\n"
            f"params: {keys}\n"
            f"Desktop: type /create-image to open the composer panel.\n"
            f"CLI: /create-image <prompt>"
        )
    if provider is None:
        return f"No image_gen provider registered for '{provider_name}'."
    try:
        result = provider.generate(prompt=prompt, model=model)
    except Exception as exc:
        return f"generate failed: {exc}"
    if not isinstance(result, dict):
        return "generate returned non-dict"
    if not result.get("success"):
        return f"error: {result.get('error') or result}"
    image = result.get("image") or ""
    return f"ok\nmodel: {result.get('model')}\nimage: {image}"


def register(ctx) -> None:
    ctx.register_command(
        "create-image",
        handler=_handle_create_image,
        description="Open create-image panel (Desktop) or generate with prompt (CLI)",
        args_hint="[prompt]",
    )
