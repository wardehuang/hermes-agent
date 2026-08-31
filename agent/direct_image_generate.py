"""One-shot create-image panel send: skip the main model, run image_generate.

When the Desktop create-image bar is open, composer middleware writes
``direct=true`` plus the prompt into ``create_image_panel.json`` and submits
the raw user prompt as a normal chat turn. This module intercepts that turn
before the first provider call, injects a synthetic ``image_generate`` tool
call, and returns a short closing line so the transcript stays
role-alternation safe.

The image card in chat is the standard tool row — same renderer as a
model-issued ``image_generate``.

A fallback still recognizes the older force-tool English instruction so a
Desktop build that has not picked up the new plugin.js can skip the main
model after a gateway restart.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from types import SimpleNamespace
from typing import Any, Optional

from agent.message_content import flatten_message_text
from agent.message_metadata import append_message

logger = logging.getLogger(__name__)

_DIRECT_OK = "已生成。"
_DIRECT_DISABLED = "image_generate 未启用，无法直发生图。"
_FORCE_TOOL_MARK = "Call the image_generate tool exactly once"
_FORCE_TOOL_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def maybe_run_direct_image_generate(
    agent,
    messages: list,
    *,
    effective_task_id: str,
    conversation_history: Optional[list] = None,
    user_message: Any = None,
) -> Optional[str]:
    """Run panel-direct image_generate if this turn requested it.

    Returns a closing ``final_response`` when the turn was handled (skip the
    LLM). Returns ``None`` to fall through to the normal provider loop.
    """
    from tools.image_generation_tool import consume_panel_direct_call

    incoming = flatten_message_text(user_message).strip()
    args = consume_panel_direct_call(
        task_id=effective_task_id,
        user_prompt=incoming,
    )
    if args is None:
        args = _args_from_force_tool_prompt(incoming)
    if args is None:
        return None

    valid = getattr(agent, "valid_tool_names", None) or set()
    if "image_generate" not in valid:
        logger.warning("create-image direct send but image_generate is not enabled")
        return _DIRECT_DISABLED

    prompt = str(args.get("prompt") or incoming).strip()
    if not prompt:
        return None

    args["prompt"] = prompt
    call_id = f"call_{uuid.uuid4().hex[:12]}"
    assistant_message = SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id=call_id,
                type="function",
                function=SimpleNamespace(
                    name="image_generate",
                    arguments=json.dumps(args, ensure_ascii=False),
                ),
            )
        ],
    )

    assistant_msg = agent._build_assistant_message(assistant_message, "tool_calls")
    append_message(messages, assistant_msg)
    try:
        agent._persist_session(messages, conversation_history)
    except Exception:
        logger.debug("direct image_generate persist before tool failed", exc_info=True)

    logger.info("create-image direct send: skipping main model, running image_generate")
    try:
        agent._execute_tool_calls(
            assistant_message, messages, effective_task_id, 0
        )
    except Exception as exc:
        logger.exception("direct image_generate failed")
        return f"image_generate failed: {exc}"

    try:
        agent._persist_session(messages, conversation_history)
    except Exception:
        logger.debug("direct image_generate persist after tool failed", exc_info=True)

    return _closing_line(messages)


def _args_from_force_tool_prompt(text: str) -> Optional[dict]:
    if _FORCE_TOOL_MARK not in (text or ""):
        return None
    match = _FORCE_TOOL_JSON.search(text)
    if not match:
        return None
    try:
        args = json.loads(match.group(1))
    except Exception:
        return None
    if not isinstance(args, dict):
        return None
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return None
    args["prompt"] = prompt
    return args


def _closing_line(messages: list) -> str:
    last = messages[-1] if messages else None
    if not isinstance(last, dict) or last.get("role") != "tool":
        return _DIRECT_OK
    try:
        payload = json.loads(last.get("content") or "")
    except Exception:
        return _DIRECT_OK
    if isinstance(payload, dict) and payload.get("success") is False:
        return str(payload.get("error") or "image_generate failed")
    return _DIRECT_OK
