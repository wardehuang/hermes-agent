"""Ultra Plan — agent half.

Desktop sends only the mode id (and Continue/Build payloads). Notes ride
``pre_llm_call`` → the model-facing user bytes. Plan mode is gated by
``pre_tool_call``.
"""

from __future__ import annotations

import logging

from . import enforce
from .modes import is_slash_shaped, note_for
from .store import load_store

__all__ = ["register"]

PLUGIN_NAME = "ultra-plan"
VERSION = "1.0.0"
logger = logging.getLogger("plugins.ultra-plan")


def _emit(message: str) -> None:
    logger.info("%s", message)


def register(ctx):  # noqa: ANN001 - PluginContext from hermes_cli.plugins
    store = load_store(PLUGIN_NAME)

    def on_pre_llm_call(session_id: str = "", user_message=None, **kwargs):
        try:
            text = user_message if isinstance(user_message, str) else ""
            if is_slash_shaped(text.strip()):
                return None
            if isinstance(user_message, dict):
                author = str(user_message.get("author") or "")
                if author and author != "user":
                    return None
            pending = store.pop_pending(session_id)
            mode = store.get_mode(session_id, consume_next=True)
            note = note_for(mode, pending)
            _emit(
                f"pre_llm_call mode={mode} pending={bool(pending)} "
                f"session={session_id or '-'} note={bool(note)}"
            )
            if not note:
                return None
            return {"context": note}
        except Exception as exc:
            _emit(f"pre_llm_call failed: {exc!r}")
            return None

    ctx.register_hook("pre_llm_call", on_pre_llm_call)

    def on_pre_tool_call(tool_name: str = "", args=None, session_id: str = "", **kwargs):
        try:
            if store.get_mode(session_id) != "plan":
                return None
            message = enforce.plan_block_message(tool_name, args)
            if message:
                _emit(f"plan-block tool={tool_name} session={session_id or '-'}")
                return {"action": "block", "message": message}
        except Exception as exc:
            _emit(f"pre_tool_call failed: {exc!r}")
        return None

    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    _emit(f"register ver=v{VERSION} enforce={enforce.plan_enforcement_enabled()}")
