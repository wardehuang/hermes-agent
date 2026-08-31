"""Video gen backend routed through the named Hermes provider ``grok2api``."""

from __future__ import annotations

import base64
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from agent.video_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_RESOLUTION,
    VideoGenProvider,
    error_response,
    save_bytes_video,
    save_url_video,
    success_response,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "grok2api"
DEFAULT_MODEL = "Web/grok-imagine-video"
DEFAULT_DURATION = 8
POLL_INTERVAL_S = 5.0
POLL_DEADLINE_S = 600.0
MAX_REFERENCE_IMAGES = 8
VALID_ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3")
VALID_RESOLUTIONS = ("480p", "720p", "1080p")


def _load_video_gen_section() -> Dict[str, Any]:
    from hermes_cli.config import load_config

    cfg = load_config()
    section = cfg.get("video_gen") if isinstance(cfg, dict) else None
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
    from agent.secret_scope import get_secret

    api_key = (get_secret(key_env) or "").strip()
    if not api_key:
        raise RuntimeError(f"{key_env} is empty")
    return base, api_key


def _resolve_model(explicit: Optional[str] = None) -> str:
    requested = str(explicit or "").strip()
    if requested:
        return requested
    section = _load_video_gen_section()
    top = section.get("model")
    if isinstance(top, str) and top.strip():
        return top.strip()
    nested = section.get(PROVIDER_NAME) if isinstance(section.get(PROVIDER_NAME), dict) else {}
    nested_model = nested.get("model") if isinstance(nested, dict) else None
    if isinstance(nested_model, str) and nested_model.strip():
        return nested_model.strip()
    return DEFAULT_MODEL


def _auth_headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _image_ref_to_input(value: str) -> Optional[Dict[str, str]]:
    ref = (value or "").strip()
    if not ref:
        return None
    lower = ref.lower()
    if lower.startswith(("http://", "https://", "data:image/")):
        return {"url": ref}

    from agent.file_safety import raise_if_read_blocked

    raise_if_read_blocked(ref)
    path = Path(ref).expanduser()
    if not path.is_file():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    if not mime.startswith("image/"):
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"url": f"data:{mime};base64,{encoded}"}


def _same_origin(url: str, base_url: str) -> bool:
    left = urlparse(url)
    right = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    return bool(left.netloc) and left.netloc.lower() == (right.netloc or "").lower()


def _materialize_video(url: str, *, api_key: str, base_url: str) -> str:
    if _same_origin(url, base_url):
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=180,
        )
        response.raise_for_status()
        return str(save_bytes_video(response.content, prefix=PROVIDER_NAME))
    return str(save_url_video(url, prefix=PROVIDER_NAME))


class Grok2apiVideoGenProvider(VideoGenProvider):
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
        return [
            {
                "id": DEFAULT_MODEL,
                "display": "Grok Web Imagine Video",
                "speed": "~60-240s",
                "strengths": "Text-to-video and image-to-video via grok2api",
                "modalities": ["text", "image"],
            }
        ]

    def default_model(self) -> Optional[str]:
        return _resolve_model()

    def capabilities(self) -> Dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "aspect_ratios": list(VALID_ASPECT_RATIOS),
            "resolutions": list(VALID_RESOLUTIONS),
            "max_duration": 15,
            "min_duration": 1,
            "supports_audio": False,
            "supports_negative_prompt": False,
            "max_reference_images": MAX_REFERENCE_IMAGES,
        }

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Grok2API",
            "badge": "local",
            "tag": "Grok Imagine video via providers.grok2api",
            "env_vars": [],
        }

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        duration: Optional[int] = None,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        resolution: str = DEFAULT_RESOLUTION,
        negative_prompt: Optional[str] = None,
        audio: Optional[bool] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            return error_response(
                error="prompt is required",
                error_type="invalid_input",
                provider=PROVIDER_NAME,
            )

        try:
            base_url, api_key = _resolve_endpoint()
        except Exception as exc:
            return error_response(
                error=str(exc),
                error_type="auth_required",
                provider=PROVIDER_NAME,
                prompt=prompt,
            )

        model_id = _resolve_model(model)
        ratio = str(aspect_ratio or DEFAULT_ASPECT_RATIO).strip()
        if ratio not in VALID_ASPECT_RATIOS:
            return error_response(
                error=f"aspect_ratio must be one of {', '.join(VALID_ASPECT_RATIOS)}",
                error_type="invalid_input",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
            )
        res = str(resolution or DEFAULT_RESOLUTION).strip().lower()
        if res not in VALID_RESOLUTIONS:
            return error_response(
                error=f"resolution must be one of {', '.join(VALID_RESOLUTIONS)}",
                error_type="invalid_input",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        if duration is not None and (duration < 1 or duration > 15):
            return error_response(
                error="duration must be between 1 and 15 seconds",
                error_type="invalid_input",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        image_input = None
        if isinstance(image_url, str) and image_url.strip():
            image_input = _image_ref_to_input(image_url)
            if image_input is None:
                return error_response(
                    error="image_url must be an http(s) URL, data URI, or local image file",
                    error_type="invalid_image_url",
                    provider=PROVIDER_NAME,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=ratio,
                )

        refs: List[Dict[str, str]] = []
        for raw in reference_image_urls or []:
            cleaned = str(raw or "").strip()
            if not cleaned:
                continue
            converted = _image_ref_to_input(cleaned)
            if converted is None:
                return error_response(
                    error="reference_image_urls entries must be http(s) URLs, data URIs, or local image files",
                    error_type="invalid_reference_image_urls",
                    provider=PROVIDER_NAME,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=ratio,
                )
            refs.append(converted)
        if len(refs) > MAX_REFERENCE_IMAGES:
            return error_response(
                error=f"reference_image_urls supports at most {MAX_REFERENCE_IMAGES} images",
                error_type="too_many_references",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=ratio,
            )
        if image_input is not None and refs:
            return error_response(
                error="image_url and reference_image_urls cannot be combined",
                error_type="conflicting_inputs",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        payload: Dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "aspect_ratio": ratio,
            "resolution": res,
        }
        if duration is not None:
            payload["duration"] = duration
        if image_input is not None:
            payload["image"] = image_input
        if refs:
            payload["reference_images"] = refs

        headers = _auth_headers(api_key)
        try:
            created = requests.post(
                f"{base_url}/videos/generations",
                headers=headers,
                json=payload,
                timeout=60,
            )
            if not created.ok:
                return error_response(
                    error=f"{PROVIDER_NAME} video API {created.status_code}: {created.text[:400]}",
                    error_type="api_error",
                    provider=PROVIDER_NAME,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=ratio,
                )
            body = created.json()
        except Exception as exc:
            logger.debug("%s video submit failed", PROVIDER_NAME, exc_info=True)
            return error_response(
                error=f"{PROVIDER_NAME} video submit failed: {exc}",
                error_type=type(exc).__name__,
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        request_id = str(body.get("request_id") or "").strip()
        if not request_id:
            return error_response(
                error=f"{PROVIDER_NAME} video response lacked request_id",
                error_type="empty_response",
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        deadline = time.monotonic() + POLL_DEADLINE_S
        poll_body: Dict[str, Any] = {}
        status = ""
        try:
            while time.monotonic() < deadline:
                polled = requests.get(
                    f"{base_url}/videos/{request_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=30,
                )
                if not polled.ok:
                    return error_response(
                        error=f"{PROVIDER_NAME} poll {polled.status_code}: {polled.text[:400]}",
                        error_type="api_error",
                        provider=PROVIDER_NAME,
                        model=model_id,
                        prompt=prompt,
                        aspect_ratio=ratio,
                    )
                parsed = polled.json()
                poll_body = parsed if isinstance(parsed, dict) else {}
                status = str(poll_body.get("status") or "").strip().lower()
                if status == "done":
                    break
                if status in {"failed", "error", "expired", "cancelled", "canceled"}:
                    err = poll_body.get("error") if isinstance(poll_body.get("error"), dict) else {}
                    message = str(err.get("message") or poll_body.get("message") or status)
                    return error_response(
                        error=message,
                        error_type=f"grok2api_{status}",
                        provider=PROVIDER_NAME,
                        model=str(poll_body.get("model") or model_id),
                        prompt=prompt,
                        aspect_ratio=ratio,
                    )
                time.sleep(POLL_INTERVAL_S)
            else:
                return error_response(
                    error=f"Timed out waiting for {PROVIDER_NAME} video after {int(POLL_DEADLINE_S)}s",
                    error_type="timeout",
                    provider=PROVIDER_NAME,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=ratio,
                )
        except Exception as exc:
            logger.debug("%s video poll failed", PROVIDER_NAME, exc_info=True)
            return error_response(
                error=f"{PROVIDER_NAME} video poll failed: {exc}",
                error_type=type(exc).__name__,
                provider=PROVIDER_NAME,
                model=model_id,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        video = poll_body.get("video") if isinstance(poll_body.get("video"), dict) else {}
        video_url = str(video.get("url") or "").strip()
        if not video_url:
            return error_response(
                error=f"{PROVIDER_NAME} completed without a video URL",
                error_type="empty_response",
                provider=PROVIDER_NAME,
                model=str(poll_body.get("model") or model_id),
                prompt=prompt,
                aspect_ratio=ratio,
            )

        try:
            video_ref = _materialize_video(video_url, api_key=api_key, base_url=base_url)
        except Exception:
            logger.debug("%s: saving video locally failed; returning URL", PROVIDER_NAME, exc_info=True)
            video_ref = video_url

        out_duration = video.get("duration")
        if not isinstance(out_duration, int):
            out_duration = duration or DEFAULT_DURATION
        return success_response(
            video=video_ref,
            model=str(poll_body.get("model") or model_id),
            prompt=prompt,
            modality="image" if image_input is not None or refs else "text",
            aspect_ratio=ratio,
            duration=out_duration,
            provider=PROVIDER_NAME,
            extra={"request_id": request_id, "resolution": res, "base_url": base_url},
        )


def register(ctx) -> None:
    ctx.register_video_gen_provider(Grok2apiVideoGenProvider())
