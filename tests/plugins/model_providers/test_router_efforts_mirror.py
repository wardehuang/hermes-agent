"""The Router efforts disk mirror survives a bad or stale ``ts``.

Regression for upstream's deletion of ``_DISK_TTL_SECONDS`` (208bd0b65a): the constant's two readers
stayed behind, so an unparseable ``ts`` made ``_load_disk`` swallow the NameError in its own
``except Exception`` and silently drop the mirror, while a stale mirror raised NameError on the
codex-transport hot path (``_efforts_cache_only``). Both lines implement the same policy — a past-
TTL verdict beats no verdict, served while a background refresh runs.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import pytest

EFFORTS = {"grok-4.6": ["low", "high"]}


def _router_module() -> Any:
    from providers import get_provider_profile

    profile = get_provider_profile("router")
    assert profile is not None, "router profile must be registered"

    return sys.modules[type(profile).__module__]


@pytest.fixture
def mirror(monkeypatch):
    """Isolated mirror file + reset once-only state + a recorded background refresh."""
    mod = _router_module()

    monkeypatch.setattr(mod, "_efforts_cache", None)
    monkeypatch.setattr(mod, "_disk_checked", False)
    monkeypatch.setattr(mod, "_state_by_home", {})
    warmed: list[bool] = []
    monkeypatch.setattr(mod, "_warm_efforts_async", lambda: warmed.append(True))

    path = mod._disk_path()
    assert path is not None, "HERMES_HOME must resolve under the test isolation"
    path.parent.mkdir(parents=True, exist_ok=True)

    return mod, path, warmed


def _write_mirror(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_unparseable_ts_is_treated_as_the_ttl_not_a_dropped_mirror(mirror):
    mod, path, _warmed = mirror
    _write_mirror(path, {"ts": "not-a-number", "efforts": EFFORTS})

    efforts, age = mod._load_disk()

    assert efforts == EFFORTS
    assert age == mod._DISK_TTL_SECONDS


def test_unparseable_ts_mirror_is_served_and_refreshed(mirror):
    mod, path, warmed = mirror
    _write_mirror(path, {"ts": "not-a-number", "efforts": EFFORTS})

    assert mod._efforts_cache_only() == EFFORTS
    assert warmed == [True]


def test_stale_mirror_is_served_and_refreshed(mirror):
    mod, path, warmed = mirror
    _write_mirror(path, {"ts": time.time() - mod._DISK_TTL_SECONDS - 60, "efforts": EFFORTS})

    assert mod._efforts_cache_only() == EFFORTS
    assert warmed == [True]


def test_fresh_mirror_is_served_without_a_refresh(mirror):
    mod, path, warmed = mirror
    _write_mirror(path, {"ts": time.time(), "efforts": EFFORTS})

    assert mod._efforts_cache_only() == EFFORTS
    assert warmed == []
