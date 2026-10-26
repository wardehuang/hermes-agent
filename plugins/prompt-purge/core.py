"""prompt-purge — 运行时枚举 harness prompt 段，按 profile 剥离；模板拼接后写入 SOUL.md。

设计
----
* **不改源码**：monkey-patch ``agent.system_prompt.build_system_prompt_parts``。
  ``build_system_prompt()`` 在模块内直接调用它，patch 模块属性即生效。
* **运行时枚举**：每次真实构建时把每个 tier 按 ``\\n\\n`` 切开，登记段首 / 字符数 / tier。
  上游改文案时选项自动跟着变，插件不需要维护选项表。
* **per-profile**：配置读 ``<profile home>/prompt-purge.json``，没有文件 = 该 profile 不启用。
* **注入**：模板拼接后写入 ``<profile home>/SOUL.md``（先备份），因为 SOUL.md 占据
  system prompt 第一位。
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from hashlib import sha1
from pathlib import Path
from typing import Any, Iterable

PLUGIN_ID = "prompt-purge"
STATE_FILE = "prompt-purge.json"
SOUL_FILE = "SOUL.md"
SOUL_BACKUP = "SOUL.md.pre-purge.bak"
TEMPLATES_DIR = Path(__file__).parent / "templates"

_ORIG = None
_APPLIED = False
# seg_id -> {id, head, chars, tier, count}
_SEEN: dict[str, dict[str, Any]] = {}


# ── 路径 ──────────────────────────────────────────────────────────────────
def profiles_root() -> Path:
    """<hermes root> —— 含 profiles/ 的那一层。"""
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    if (home / "profiles").is_dir():
        return home
    if home.parent.name == "profiles":
        return home.parent.parent
    return home


def profile_home(name: str) -> Path:
    root = profiles_root()
    if name in ("", "default"):
        return root
    return root / "profiles" / name


def list_profiles() -> list[str]:
    root = profiles_root()
    out = []
    if (root / "config.yaml").is_file():
        out.append("default")
    pdir = root / "profiles"
    if pdir.is_dir():
        out.extend(sorted(d.name for d in pdir.iterdir()
                          if d.is_dir() and not d.name.startswith(".") and (d / "config.yaml").is_file()))
    return out


def current_profile_name() -> str:
    """本进程/本请求所属的 profile（gateway 会按请求绑定 HERMES_HOME）。"""
    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home())
    except Exception:
        return "default"
    if home.parent.name == "profiles":
        return home.name
    return "default"


def _agent_home(agent: Any) -> Path | None:
    try:
        from agent.system_prompt import _agent_home as _h

        return _h(agent)
    except Exception:
        return None


# ── 状态 ──────────────────────────────────────────────────────────────────
def load_state(profile: str) -> dict[str, Any]:
    path = profile_home(profile) / STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"profile": profile, "drop": [], "templates": []}
    if not isinstance(data, dict):
        return {"profile": profile, "drop": [], "templates": []}
    drop = [str(x) for x in data.get("drop") or [] if isinstance(x, str)]
    tpls = [str(x) for x in data.get("templates") or [] if isinstance(x, str)]
    return {"profile": profile, "drop": drop, "templates": tpls}


def save_state(profile: str, drop: Iterable[str], templates: Iterable[str]) -> dict[str, Any]:
    home = profile_home(profile)
    home.mkdir(parents=True, exist_ok=True)
    state = {
        "profile": profile,
        "drop": [s for s in (str(x) for x in drop) if s],
        "templates": [s for s in (str(x) for x in templates) if s],
    }
    (home / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


# ── 段枚举 ────────────────────────────────────────────────────────────────
def _seg_id(head: str) -> str:
    return sha1(head.encode("utf-8", "replace")).hexdigest()[:12]


def _profile_of(agent: Any = None) -> str:
    """当前构建所属的 profile —— 优先 agent 自带的 home，回退到上下文里的 HERMES_HOME。"""
    home = None
    for attr in ("home", "hermes_home", "_home"):
        try:
            val = getattr(agent, attr, None)
            if val:
                home = Path(val)
                break
        except Exception:
            continue
    if home is None:
        try:
            from hermes_constants import get_hermes_home

            home = Path(get_hermes_home())
        except Exception:
            return "default"
    return home.name if home.parent.name == "profiles" else "default"


def _bucket(profile: str) -> dict[str, dict[str, Any]]:
    """每个 profile 一份独立的段表 —— 切 profile 不会看到另一个 profile 的段。"""
    return _SEEN.setdefault(profile or "default", {})


def _scan(parts: dict[str, str], profile: str = "", soul_text: str = "") -> None:
    bucket = _bucket(profile)
    for tier, text in parts.items():
        if not isinstance(text, str) or not text:
            continue
        for section in text.split("\n\n"):
            body = section.strip()
            if not body:
                continue
            head = body.split("\n", 1)[0][:160]
            sid = _seg_id(head)
            # source 在扫描时定：段首出现在该 profile 的 SOUL.md 里 = soul，否则 harness。
            source = "soul" if (soul_text and head[:80] and head[:80] in soul_text) else "harness"
            rec = bucket.get(sid)
            if rec is None:
                bucket[sid] = {
                    "id": sid, "head": head, "chars": len(body), "tier": tier,
                    "count": 1, "text": body, "source": source,
                }
            else:
                rec["count"] += 1
                if len(body) > rec["chars"]:
                    rec["chars"] = len(body)
                    rec["text"] = body
                rec["tier"] = tier
                rec["source"] = source


# 属于「稳定层但删了会缺功能」的段：记忆指引、技能安全规则、工具链探测、工作区快照。
# 这些不是 harness 的框架话术，列进删除列表只会误导。
KEEP_PREFIXES: tuple[str, ...] = (
    "You have persistent memory",
    "## Skill Safety Rule",
    "Python toolchain",
    "Workspace (snapshot at session start",
    "## Skills",
    "<available_skills>",
)


def _droppable(item: dict[str, Any]) -> bool:
    """只有 stable 层的 harness 段才是可删的框架话术。"""
    if item.get("source") != "harness" or item.get("tier") != "stable":
        return False
    head = str(item.get("head") or "")
    return not any(head.startswith(k) for k in KEEP_PREFIXES)


def sections(profile: str | None = None) -> list[dict[str, Any]]:
    """已登记的全部段。

    ``source`` 区分 harness 段和 SOUL.md 自身的段 —— 后者不该出现在"删除"列表里。
    ``droppable`` 是"可安全删除"的判定（stable + harness + 不在 KEEP_PREFIXES）。
    ``text`` 是段全文（截断到 4000 字符），供前端"详情"弹窗使用。
    """
    prof = profile or current_profile_name()
    recs = _SEEN.get(prof) or {}
    order = {"stable": 0, "context": 1, "volatile": 2}
    out: list[dict[str, Any]] = []
    for rec in recs.values():
        item = dict(rec)
        item["text"] = str(item.get("text") or "")[:4000]
        item["droppable"] = _droppable(item)
        out.append(item)
    return sorted(
        out,
        key=lambda r: (0 if r["droppable"] else 1, 0 if r["source"] == "harness" else 1,
                       order.get(r["tier"], 9), -r["chars"]),
    )


def _strip(text: str, drop: list[str]) -> str:
    if not text or not drop:
        return text
    kept = [s for s in text.split("\n\n")
            if not any(s.strip().startswith(p) for p in drop)]
    return "\n\n".join(kept)


def _drop_for(agent: Any) -> list[str]:
    home = _agent_home(agent)
    if home is None:
        # 回退到当前 profile。gateway 里 agent 可能没有 _session_db（或它指向 launch
        # home），此时 _agent_home 返回 None —— 读不到配置就等于删除从未生效。
        try:
            from hermes_constants import get_hermes_home

            home = Path(get_hermes_home())
        except Exception:
            return []
    try:
        data = json.loads((Path(home) / STATE_FILE).read_text(encoding="utf-8"))
    except Exception:
        return []
    drop = data.get("drop") if isinstance(data, dict) else None
    return [str(x) for x in drop if isinstance(x, str)] if isinstance(drop, list) else []


# ── patch ─────────────────────────────────────────────────────────────────
def patch() -> bool:
    global _ORIG, _APPLIED
    if _APPLIED:
        return True
    from agent import system_prompt as sp

    _ORIG = sp.build_system_prompt_parts

    def patched(agent: Any, system_message: Any = None):
        parts = _ORIG(agent, system_message)
        try:
            prof = _profile_of(agent)
            # 直接读当前 profile 的 SOUL.md：patched 运行时 HERMES_HOME 已绑定到该 profile。
            soul = ""
            try:
                from hermes_constants import get_hermes_home

                sp = Path(get_hermes_home()) / SOUL_FILE
                if sp.is_file():
                    soul = sp.read_text(encoding="utf-8")
            except Exception:
                soul = ""
            _scan(parts, prof, soul) if _SCAN_ENABLED else None
            drop = current_drop(agent)
            if drop:
                parts = {k: _strip(v, drop) for k, v in parts.items()}
        except Exception:
            pass
        return parts

    sp.build_system_prompt_parts = patched
    _APPLIED = True
    return True


# ── 模板 ──────────────────────────────────────────────────────────────────
def list_templates() -> list[dict[str, Any]]:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(TEMPLATES_DIR.glob("*.md")):
        try:
            out.append({"name": p.stem, "chars": p.stat().st_size})
        except OSError:
            continue
    return out


def read_template(name: str) -> str:
    p = TEMPLATES_DIR / f"{name}.md"
    if not p.is_file():
        raise FileNotFoundError(name)
    return p.read_text(encoding="utf-8")


def template_path(name: str) -> Path:
    """模板文件路径（不要求存在）。"""
    safe = str(name or "").strip().replace("/", "_").replace("\\", "_")
    if not safe:
        raise ValueError("empty template name")
    return TEMPLATES_DIR / f"{safe}.md"


def open_in_editor(name: str) -> dict[str, Any]:
    """用 VS Code 打开模板；没有 code 命令时退回系统默认程序。"""
    import shutil
    import subprocess

    path = template_path(name)
    if not path.is_file():
        raise FileNotFoundError(name)
    opened_with = "code"
    exe = shutil.which("code") or shutil.which("code.cmd")
    if exe:
        subprocess.Popen([exe, str(path)], close_fds=True)
    else:
        opened_with = "default"
        if hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)], close_fds=True)
    return {"ok": True, "path": str(path), "opened_with": opened_with}


def write_template(name: str, content: str) -> None:
    name = name.strip().replace("/", "_").replace("\\", "_")
    if not name:
        raise ValueError("empty template name")
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    (TEMPLATES_DIR / f"{name}.md").write_text(content, encoding="utf-8")


def delete_template(name: str) -> bool:
    p = TEMPLATES_DIR / f"{name}.md"
    if not p.is_file():
        return False
    p.unlink()
    return True


def rename_template(old: str, new: str) -> bool:
    src = TEMPLATES_DIR / f"{old}.md"
    if not src.is_file():
        return False
    new = new.strip().replace("/", "_").replace("\\", "_")
    if not new:
        return False
    src.rename(TEMPLATES_DIR / f"{new}.md")
    return True


def compose(templates: Iterable[str]) -> str:
    parts = []
    for name in templates:
        try:
            body = read_template(name).strip()
        except FileNotFoundError:
            continue
        if body:
            parts.append(body)
    return "\n\n".join(parts)


# ── 应用 / 还原 ───────────────────────────────────────────────────────────
def apply_to_soul(profile: str, templates: Iterable[str]) -> dict[str, Any]:
    home = profile_home(profile)
    home.mkdir(parents=True, exist_ok=True)
    text = compose(templates)
    if not text:
        raise ValueError("no template content to write")
    soul = home / SOUL_FILE
    backup = home / SOUL_BACKUP
    if soul.is_file() and not backup.exists():
        shutil.copy2(soul, backup)
    soul.write_text(text, encoding="utf-8", newline="\n")
    return {"profile": profile, "path": str(soul), "chars": len(text)}


def revert_soul(profile: str) -> dict[str, Any]:
    home = profile_home(profile)
    backup = home / SOUL_BACKUP
    soul = home / SOUL_FILE
    if not backup.is_file():
        raise FileNotFoundError("no backup to restore")
    shutil.copy2(backup, soul)
    return {"profile": profile, "path": str(soul), "restored": True}


# ── 预览 ──────────────────────────────────────────────────────────────────
def _preview_inner(profile: str | None, templates: list[str], drop: list[str]) -> dict[str, Any]:
    """构造一个真实 agent（不调模型），返回该 profile 新会话会发出的完整 system prompt。

    注入效果用临时替换 ``load_soul_md`` 模拟，不写磁盘。
    """
    from hermes_cli.config import load_config_readonly

    prof = profile or current_profile_name()
    home = profile_home(prof)
    overlay = compose(templates) if templates else ""
    soul_path = home / SOUL_FILE

    global _SCAN_ENABLED
    prev_scan = _SCAN_ENABLED
    if overlay:
        # overlay 的段不属于真实 SOUL.md，扫进段表会污染删除列表
        _SCAN_ENABLED = False

    # 1) 临时让 load_soul_md 返回拼接后的模板（预览不落盘）
    from agent import prompt_builder as pb

    orig_load = pb.load_soul_md
    if overlay:
        pb.load_soul_md = lambda *a, **k: overlay  # type: ignore[assignment]

    # 2) 临时让 _drop_for 用本次请求的 drop（预览不依赖已保存的配置）
    global _PREVIEW_DROP
    prev_drop = _PREVIEW_DROP
    _PREVIEW_DROP = list(drop or [])

    env_prev = os.environ.get("HERMES_HOME")
    token = None
    try:
        try:
            from hermes_constants import set_hermes_home_override  # type: ignore

            token = set_hermes_home_override(str(home))
        except Exception:
            os.environ["HERMES_HOME"] = str(home)

        cfg = load_config_readonly() or {}
        model_cfg = cfg.get("model") or {}
        provider = str(model_cfg.get("provider") or "")
        base_url = str(model_cfg.get("base_url") or "")
        api_mode = str(model_cfg.get("api_mode") or "")
        model = str(model_cfg.get("default") or "")
        key_env = str(model_cfg.get("key_env") or "")

        api_key = ""
        try:
            env_file = home / ".env"
            if key_env and env_file.is_file():
                for line in env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith(f"{key_env}="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

        from run_agent import AIAgent

        agent = AIAgent(
            api_key=api_key, base_url=base_url, provider=provider, model=model,
            api_mode=api_mode or "chat_completions", platform="cli",
            quiet_mode=True,
        )
        text = agent._build_system_prompt(None)
        return {
            "profile": prof,
            "chars": len(text),
            "text": text,
            "overlay_chars": len(overlay),
            "drop": list(drop or []),
            "soul_md_chars": len(overlay) if overlay else (soul_path.stat().st_size if soul_path.is_file() else 0),
        }
    finally:
        pb.load_soul_md = orig_load  # type: ignore[assignment]
        _PREVIEW_DROP = prev_drop
        _SCAN_ENABLED = prev_scan
        if token is not None:
            try:
                from hermes_constants import reset_hermes_home_override  # type: ignore

                reset_hermes_home_override(token)
            except Exception:
                pass
        elif env_prev is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = env_prev


_PREVIEW_DROP: list[str] = []
# 预览时 parts 里混的是模板 overlay，不是真实 SOUL.md —— 扫进去会污染段表。
_SCAN_ENABLED = True
# preview/warm 会临时绑定 HERMES_HOME；串行化以免两个 profile 的构建交错。
_BUILD_LOCK = threading.Lock()


def preview(profile: str | None = None, templates: list[str] | None = None,
            drop: list[str] | None = None) -> dict[str, Any]:
    """串行化的 preview：同一进程内一次只构建一个 profile 的 prompt。"""
    with _BUILD_LOCK:
        return _preview_inner(profile, list(templates or []), list(drop or []))


def warm(profile: str | None = None) -> int:
    """冷启动：构造一次 agent 让 patch 枚举段。不发 LLM 请求、不落盘。"""
    prof = profile or current_profile_name()
    preview(prof, [], [])
    return len(_SEEN.get(prof) or {})


def current_drop(agent: Any = None) -> list[str]:
    """预览期间优先用请求里的 drop，否则读该 agent 的配置。"""
    if _PREVIEW_DROP:
        return _PREVIEW_DROP
    if agent is not None:
        return _drop_for(agent)
    return []


# ── 插件入口 ──────────────────────────────────────────────────────────────
def register(ctx: Any) -> None:
    patch()
