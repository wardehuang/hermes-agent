"""prompt-purge 插件入口。

核心逻辑在 ``core.py``：``plugin_api.py``（HTTP 路由）需要共享同一份状态
（``_SEEN`` 段登记表 / ``_APPLIED``），所以两边都用 ``load_core()`` 加载同一个模块实例。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

CORE_NAME = "prompt_purge_core"


def load_core():
    mod = sys.modules.get(CORE_NAME)
    if mod is not None:
        return mod
    path = Path(__file__).resolve().parent / "core.py"
    spec = importlib.util.spec_from_file_location(CORE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[CORE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def register(ctx) -> None:
    core = load_core()
    core.patch()
