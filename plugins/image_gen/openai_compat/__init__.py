"""Image gen backend for endpoints saved by the create-image plugin."""

from __future__ import annotations

import base64
import logging
import mimetypes
import sys
from pathlib import Path
from typing import Any, Optional

from agent.image_gen_provider import (
    ImageGenProvider,
    error_response,
    normalize_reference_images,
    save_b64_image,
    save_url_image,
    success_response,
)

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2] / "create-image"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import endpoints as endpoint_store

PROVIDER_NAME = endpoint_store.PROVIDER_NAME


def _data_url(data: bytes, name: str) -> str:
    mime = mimetypes.guess_type(name)[0] or "image/png"
    if not str(mime).startswith("image/"):
        mime = "image/png"
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _allowed_payload(model: dict[str, Any], aspect_ratio: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    params = endpoint_store.params_for(model)
    payload: dict[str, Any] = {}
    for key, spec in params.items():
        if key == "prompt" or not isinstance(spec, dict):
            continue
        allowed: dict[str, Any] = {}
        for item in spec.get("enum") or []:
            if isinstance(item, dict):
                value = item.get("value")
            else:
                value = item
            if value is None or str(value).strip() == "":
                continue
            allowed[str(value)] = value
        raw = kwargs.get(key)
        if (raw is None or str(raw).strip() == "") and key == "aspect_ratio":
            raw = aspect_ratio
        text = str(raw).strip() if raw is not None else ""
        if text not in allowed:
            continue
        if spec.get("type") == "integer" or key == "n":
            payload[key] = int(text)
        else:
            payload[key] = allowed[text]
    return payload


class OpenAICompatImageGenProvider(ImageGenProvider):
    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "OpenAI-compatible"

    def is_available(self) -> bool:
        try:
            return endpoint_store.is_ready()
        except Exception:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        out = []
        for item in endpoint_store.catalog_items():
            out.append(
                {
                    "id": item["model"],
                    "display": item["display"],
                    "endpoint_id": item["endpoint_id"],
                    "params": item["params"],
                    "prompt_constraints": False,
                }
            )
        return out

    def default_model(self) -> Optional[str]:
        active = endpoint_store.resolve_active()
        if active is None:
            return None
        return str(active[1].get("id") or "") or None

    def capabilities(self) -> dict[str, Any]:
        model_id = self.default_model() or ""
        caps = self.model_capabilities(model_id) if model_id else {}
        return {
            "modalities": ["text", "image"],
            "max_reference_images": 4,
            "model": model_id,
            "model_params": caps.get("params") or {},
            "model_capabilities": caps,
        }

    def model_capabilities(self, model_id: Optional[str] = None) -> dict[str, Any]:
        return endpoint_store.caps_for(None, model_id or self.default_model() or "")

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            "name": "OpenAI-compatible",
            "badge": "custom",
            "tag": "Endpoints saved in the create-image bar",
            "env_vars": [],
        }

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            return error_response(
                error="Prompt is required",
                error_type="invalid_input",
                provider=PROVIDER_NAME,
                aspect_ratio="1:1",
            )
        model_id = str(kwargs.get("model") or self.default_model() or "").strip()
        endpoint_id = str(kwargs.get("endpoint_id") or "").strip() or None
        try:
            base_url, api_key, model = endpoint_store.credentials_for(model_id, endpoint_id)
        except Exception as exc:
            return error_response(
                error=str(exc),
                error_type="auth_required",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio="1:1",
            )
        model_id = str(model.get("id") or model_id)
        extra = _allowed_payload(model, aspect_ratio, kwargs)
        native_aspect = str(extra.get("aspect_ratio") or "1:1")
        sources: list[str] = []
        if isinstance(image_url, str) and image_url.strip():
            sources.append(image_url.strip())
        sources.extend(normalize_reference_images(reference_image_urls) or [])
        is_edit = bool(sources)
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            session = endpoint_store._http_session(base_url)
            if is_edit and str(model.get("edit_body") or "") == "json":
                from plugins.image_gen.grok2api import _load_image_bytes

                images = []
                for ref in sources[:8]:
                    data, fname = _load_image_bytes(ref)
                    images.append({"url": _data_url(data, fname)})
                payload = {"model": model_id, "prompt": prompt, "image": images[0], **extra}
                if len(images) > 1:
                    payload["images"] = images[1:]
                response = session.post(
                    f"{base_url}/images/edits",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                    timeout=300,
                )
            elif is_edit:
                from plugins.image_gen.grok2api import _load_image_bytes

                files = []
                for ref in sources[:4]:
                    data, fname = _load_image_bytes(ref)
                    field = "image" if len(sources) == 1 else "image[]"
                    files.append((field, (fname, data)))
                form = {"model": model_id, "prompt": prompt}
                if "n" in extra:
                    form["n"] = str(extra["n"])
                form.update({key: str(value) for key, value in extra.items() if key != "n"})
                response = session.post(
                    f"{base_url}/images/edits",
                    headers=headers,
                    files=files,
                    data=form,
                    timeout=300,
                )
            else:
                payload = {"model": model_id, "prompt": prompt, **extra}
                response = session.post(
                    f"{base_url}/images/generations",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                    timeout=300,
                )
        except Exception as exc:
            logger.debug("openai_compat image call failed", exc_info=True)
            return error_response(
                error=f"image call failed: {exc}",
                error_type=type(exc).__name__,
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=native_aspect,
            )
        if not response.ok:
            return error_response(
                error=f"image API {response.status_code}: {(response.text or '')[:400]}",
                error_type="api_error",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=native_aspect,
            )
        try:
            body = response.json()
        except Exception:
            body = None
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return error_response(
                error="image API returned no image data",
                error_type="empty_response",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=native_aspect,
            )
        prefix = f"openai_compat_{model_id.replace('/', '_')}"
        paths: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json")
            url = item.get("url")
            if b64:
                try:
                    paths.append(str(save_b64_image(b64, prefix=prefix)))
                except Exception as exc:
                    if paths:
                        logger.debug("openai_compat skipped a later image", exc_info=True)
                        break
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
                    paths.append(str(save_url_image(url, prefix=prefix)))
                except Exception:
                    paths.append(str(url))
        if not paths:
            return error_response(
                error="image API response lacked b64_json and url",
                error_type="empty_response",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=native_aspect,
            )
        result_extra: dict[str, Any] = {"params": extra}
        if len(paths) > 1:
            result_extra["images"] = paths
        return success_response(
            image=paths[0],
            model=model_id,
            prompt=prompt,
            aspect_ratio=native_aspect,
            provider=PROVIDER_NAME,
            modality="image" if is_edit else "text",
            extra=result_extra,
        )


def register(ctx) -> None:
    ctx.register_image_gen_provider(OpenAICompatImageGenProvider())
