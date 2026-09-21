"""Ultra Plan catalogue — mode ids and the model-facing operating notes."""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "MODE_IDS",
    "DEFAULT_MODE",
    "LABELS",
    "is_mode",
    "is_slash_shaped",
    "note_for",
]

MODE_IDS = ("agent", "plan")
DEFAULT_MODE = "agent"
LABELS = {"agent": "Agent", "plan": "Plan"}

_SLASH_SHAPE_RE = re.compile(r"^/[^\s/]*(?:\s|$)")


def is_slash_shaped(text: str) -> bool:
    return bool(text) and bool(_SLASH_SHAPE_RE.match(text))


def is_mode(value: object) -> bool:
    return isinstance(value, str) and value in MODE_IDS


def _plan_note() -> str:
    from agent.plan_prompt import _PLAN_CRAFT, _PLAN_MODE_RULES

    return (
        "[Ultra Plan — plan mode]\n\n"
        + _PLAN_MODE_RULES
        + "\n"
        + _PLAN_CRAFT
        + "\n\nUltra Plan extras (override the interaction style above):\n"
        "- If the request is genuinely underspecified, you MUST call the "
        "clarify tool and give choices. The UI always includes Other. "
        "Never ask clarifying questions as chat prose.\n"
        "- After saving the plan markdown under `.hermes/plans/`, end your "
        "reply with ONLY this directive paragraph on its own line and "
        "nothing else in that paragraph:\n"
        '::plan{file=".hermes/plans/<exact-filename-you-saved>"}\n'
        "- Do not implement. Continue vs Build is chosen in the Ultra Plan view.\n"
    )


def _format_comments(comments: list[Any]) -> str:
    lines: list[str] = []
    for i, item in enumerate(comments, start=1):
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        body = str(item.get("body") or "").strip()
        if not quote and not body:
            continue
        lines.append(f"{i}.")
        if quote:
            lines.append(f"   Quote: {quote}")
        if body:
            lines.append(f"   Comment: {body}")
    return "\n".join(lines) if lines else "(no comments)"


def _pending_note(pending: dict[str, Any]) -> str:
    action = str(pending.get("action") or "").strip().lower()
    plan_file = str(pending.get("plan_file") or "").strip()
    comments = pending.get("comments") if isinstance(pending.get("comments"), list) else []
    packed = _format_comments(comments)
    if action == "build":
        return (
            "[Ultra Plan — Build]\n"
            "The user clicked Build. Leave plan mode. Implement the plan "
            f"at `{plan_file or '.hermes/plans/<the-plan>.md'}`.\n"
            "Apply these selection comments while implementing; they are NOT "
            "already written into the markdown:\n"
            f"{packed}\n"
            "Do not re-emit ::plan unless you must revise the plan first."
        )
    return (
        "[Ultra Plan — Continue]\n"
        "The user clicked Continue. Stay in plan mode. Revise the plan "
        f"markdown at `{plan_file or '.hermes/plans/<the-plan>.md'}` from "
        "their comments. Do not implement code or other project files.\n"
        "Comments (not written into the file; apply them as edits):\n"
        f"{packed}\n"
        "After saving, emit ::plan{file=\"...\"} again as its own paragraph."
    )


def note_for(mode: object, pending: dict[str, Any] | None = None) -> str | None:
    parts: list[str] = []
    if mode == "plan":
        parts.append(_plan_note())
    if pending:
        parts.append(_pending_note(pending))
    if not parts:
        return None
    return "\n\n".join(parts)
