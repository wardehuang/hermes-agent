"""Plan-mode mutation gate — only the plan markdown may be written.

Copied terminal classifier shape from community composer-modes (read-only
allow-list + mutating-token deny). Ultra Plan allows write_file/patch only
when the path is `.hermes/plans/*.md`.
"""

from __future__ import annotations

import os
import re
from typing import Any

__all__ = ["plan_enforcement_enabled", "plan_block_message"]

_PLAN_PATH_RE = re.compile(r"(?:^|/)\.hermes/plans/[A-Za-z0-9._-]+\.md$", re.IGNORECASE)

ALLOW_TOOLS = frozenset(
    {
        "clarify",
        "read_file",
        "search_files",
        "web_search",
        "web_extract",
        "clientfn_web_search",
        "cpa_client_web_search",
        "skill_view",
        "skills_list",
        "session_search",
        "vision_analyze",
    }
)

DENY_TOOLS = frozenset(
    {
        "browser_exec",
        "computer_use",
        "cronjob_manage",
        "process_manage",
        "delegate_task",
        "skill_manage",
        "memory",
        "todo_list",
        "image_generate",
        "video_generate",
        "text_to_speech",
        "browser_vault_fill",
        "browser_vault_save_login",
        "setup_mcp",
        "desktop_project",
        "set_theme",
    }
)

_MUTATING_NAME_RE = re.compile(
    r"(?:^|_)(write|edit|save|append|delete|remove|move|copy|create|rename|mkdir|rmdir|"
    r"install|uninstall|upload|publish|deploy|apply_patch|commit|push|format|kill|start|stop|restart|send|post)(?:_|$)",
    re.IGNORECASE,
)

_READ_ONLY_COMMAND_RE = re.compile(
    r"^\s*(?:"
    r"cat|bat|head|tail|less|more|wc|ls|dir|tree|stat|file|du|df|md5sum|sha1sum|sha256sum|"
    r"cksum|pwd|date|whoami|hostname|uname|id|echo|printf|which|type|command -v|"
    r"find|fd|grep|rg|ag|ack|sed\s+-n|awk|sort|uniq|cut|tr|join|paste|nl|column|jq|yq|xmllint|"
    r"diff|cmp|comm|basename|dirname|realpath|readlink|seq|expr|bc|test|\[|true|false|"
    r"git\s+(?:status|log|show|diff|branch|remote|rev-parse|describe|blame|ls-files|ls-tree|"
    r"cat-file|shortlog|tag|stash\s+list|config\s+--get|config\s+--list|name-rev|for-each-ref|"
    r"worktree\s+list|submodule\s+status|fsck|reflog|whatchanged|grep|count-objects)|"
    r"hg\s+(?:status|log|diff|summary)|svn\s+(?:status|info|log|diff)|"
    r"(?:python|python3|node|npm|pnpm|yarn|bun|pip|pip3|uv|cargo|go|dotnet|java|deno|rustc|"
    r"tsc|npx|git|gh|docker|kubectl|hermes)\s+(?:--version|-V|-h|--help)\b|"
    r"npm\s+(?:ls|list|view|info|outdated|why|config\s+get)|"
    r"pnpm\s+(?:ls|list|why|outdated)|"
    r"pip\s+(?:list|show|freeze|check)|"
    r"gh\s+(?:pr\s+(?:view|list|diff|checks)|issue\s+(?:view|list)|repo\s+view|run\s+(?:view|list)|api|auth\s+status)|"
    r"docker\s+(?:ps|images|inspect|logs|version|info)|"
    r"kubectl\s+(?:get|describe|logs|version|config\s+view)|"
    r"systemctl\s+(?:status|list-units|is-active)|"
    r"open|code|explorer|start\s+\"\"|env"
    r")\b"
)

_MUTATING_TOKEN_RE = re.compile(
    r"(?:>>?|\|\s*tee\b|\btee\b|\bdd\b|\btruncate\b|\bshred\b|\bchmod\b|\bchown\b|\bchgrp\b|"
    r"\bumask\b|\bln\b|\bmv\b|\bcp\b|\brm\b|\brmdir\b|\bmkdir\b|\btouch\b|\binstall\b|\brsync\b|"
    r"\bscp\b|\bsed\s+-i|\bperl\s+-i|\bpython\s+-c|\bpython3\s+-c|\bnode\s+-e|\bsudo\b|\bsu\b|"
    r"-delete\b|-exec\b|-execdir\b|-ok\b|-fprint|\btruncate\b|"
    r"\bsystemctl\s+(?:start|stop|restart|enable|disable)\b|\bservice\b|\bgit\s+(?:add|commit|"
    r"push|pull|fetch|merge|rebase|checkout|switch|restore|reset|clean|apply|am|cherry-pick|"
    r"stash(?!\s+list)|tag\s+-|remote\s+(?:add|remove|set-url)|init|clone|config\s+(?!--get|--list))|"
    r"\bnpm\s+(?:i|install|ci|run|test|start|audit\s+fix|publish|link|uninstall)\b|"
    r"\bpnpm\s+(?:i|install|add|remove|run|test|publish)\b|\byarn\s+(?:add|install|run)\b|"
    r"\bpip3?\s+(?:install|uninstall|download)\b|\buv\s+(?:pip|sync|add|remove)\b|"
    r"\bcargo\s+(?:install|build|run|test|add|remove|publish)\b|\bgo\s+(?:build|run|install|test|mod)\b|"
    r"\bdocker\s+(?:run|build|exec|rm|stop|start|compose\s+(?:up|down|build|run))\b|"
    r"\bkubectl\s+(?:apply|delete|create|edit|exec|patch|scale|rollout)\b|"
    r"\bgh\s+(?:pr\s+(?:create|merge|close|comment|edit|checkout)|issue\s+(?:create|close|comment|edit)|"
    r"release\s+create|repo\s+(?:create|delete|clone|fork)|workflow\s+run)\b|"
    r"\bhermes\s+(?:plugins\s+(?:install|remove|enable|disable|update)|cron|config\s+set|update)\b|"
    r"\bdel\b|\berase\b|\brd\s+/|\bren\b|\bmove\b|\bcopy\b|\btype\s+>\b)"
)

_SEGMENT_SPLIT_RE = re.compile(r"(?:&&|\|\||;|\||\n)")

_BLOCK = (
    "[ultra-plan] Plan mode may only write the plan markdown under "
    "`.hermes/plans/*.md`. This call was blocked. Inspect with read-only "
    "tools, call clarify if the request is underspecified, and save the plan "
    "file. Do not implement other files until the user clicks Build."
)


def plan_enforcement_enabled() -> bool:
    return str(os.environ.get("HERMES_ULTRA_PLAN_ENFORCE", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def is_plan_markdown_path(path: str) -> bool:
    if not path or ".." in path.replace("\\", "/"):
        return False
    return bool(_PLAN_PATH_RE.search(path.replace("\\", "/")))


def _terminal_is_read_only(command: str) -> bool:
    if not command.strip():
        return False
    if _MUTATING_TOKEN_RE.search(command):
        return False
    for segment in _SEGMENT_SPLIT_RE.split(command):
        if not segment.strip():
            continue
        if not _READ_ONLY_COMMAND_RE.match(segment):
            return False
    return True


def plan_block_message(tool_name: str, args: object) -> str | None:
    if not plan_enforcement_enabled():
        return None
    if not tool_name:
        return None
    name = str(tool_name)
    if name in {"write_file", "patch"}:
        path = ""
        if isinstance(args, dict):
            path = str(args.get("path") or "")
        if is_plan_markdown_path(path):
            return None
        return _BLOCK
    if name == "terminal":
        command = ""
        if isinstance(args, dict):
            command = str(args.get("command") or "")
        if _terminal_is_read_only(command):
            return None
        return _BLOCK
    if name in ALLOW_TOOLS:
        return None
    if name in DENY_TOOLS or _MUTATING_NAME_RE.search(name):
        return _BLOCK
    return None
