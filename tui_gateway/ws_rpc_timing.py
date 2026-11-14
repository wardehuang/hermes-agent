"""Timing diagnostics for the WebSocket RPC lane (temporary).

Added to place the 2-5 s gap between a Desktop ``setup.*`` request being sent and its handler starting right after a
profile switch, and to show how long the ``model.options`` / ``commands.catalog`` reads that queue ahead of it hold the
serial lane. Remove once the stall is located and fixed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_log = logging.getLogger(__name__)

# Named on every arrival and completion, whatever their duration: the readiness checks (``setup.*``), and the catalog
# reads that queue ahead of them on a shared socket after a profile switch.
_ALWAYS_TIMED_METHODS = frozenset({"model.options", "commands.catalog"})
# Any other request whose dispatch ran this long is named too, so whatever held the serial lane ahead of a later
# request shows up.
_SLOW_DISPATCH_S = 0.2
# Event-loop lateness worth reporting: a blocked loop delays reading frames as well as dispatching them.
_LOOP_LAG_S = 0.25
_LOOP_PROBE_INTERVAL_S = 0.05

_probe: asyncio.Task | None = None


def _always_timed(method: Any) -> bool:
    return isinstance(method, str) and (method.startswith("setup.") or method in _ALWAYS_TIMED_METHODS)


def _profile_of(req: Any) -> Any:
    params = req.get("params") if isinstance(req, dict) else None
    return params.get("profile") if isinstance(params, dict) else None


def note_received(req: Any) -> None:
    """One line when a timed frame is read off the socket, so the dispatch start (its log time minus ``ms``) can be compared with when the frame actually arrived. Never params beyond the profile name."""
    method = req.get("method") if isinstance(req, dict) else None
    if _always_timed(method):
        _log.info("session-switch ws-rpc recv id=%s method=%s profile=%s", req.get("id"), method, _profile_of(req))


def log_rpc(req: Any, method: Any, elapsed_s: float) -> None:
    """One line per timed request and per request slower than ``_SLOW_DISPATCH_S``. Never params or results.

    ``elapsed_s`` spans the whole dispatch (draining check, profile routing, owner scope, handler), so comparing it with
    the handler's own ``session-switch setup.* ms=`` line shows how much time passes before the handler starts.
    """
    if elapsed_s < _SLOW_DISPATCH_S and not _always_timed(method):
        return
    _log.info(
        "session-switch ws-rpc id=%s method=%s profile=%s ms=%d",
        req.get("id") if isinstance(req, dict) else None, method, _profile_of(req), int(elapsed_s * 1000),
    )


async def _probe_loop_lag() -> None:
    loop = asyncio.get_running_loop()
    while True:
        due = loop.time() + _LOOP_PROBE_INTERVAL_S
        await asyncio.sleep(_LOOP_PROBE_INTERVAL_S)
        lag_s = loop.time() - due
        if lag_s >= _LOOP_LAG_S:
            _log.info("session-switch ws-loop-lag ms=%d", int(lag_s * 1000))


def ensure_loop_lag_probe() -> None:
    """Start the one per-process probe on the running loop (idempotent)."""
    global _probe
    if _probe is None or _probe.done():
        _probe = asyncio.get_running_loop().create_task(_probe_loop_lag())
