#!/usr/bin/env python3
"""Build an unpacked Hermes Desktop app from this source checkout (self-use path A).

Workflow:
  1. Resolve the hermes-agent repo root (parent of ``build-script/``).
  2. Refuse to pack against a stale environment: the launcher this script writes
     pins ``HERMES_DESKTOP_HERMES_ROOT``, so the app spawns THIS checkout's
     interpreter (``.venv``, or ``HERMES_DESKTOP_PYTHON``) — a checkout Python
     whose version/dependencies PM has not provisioned would ship an app that
     dies on its first turn (``No module named 'snowballstemmer'``).
  3. Prefer the official ``hermes desktop --build-only --force-build`` path so
     Electron cache repair, Windows file-lock stop, and PE integrity checks run.
  4. Fall back to ``npm install`` + ``npm run pack`` if the CLI module is not
     importable from this checkout.
  5. Write a one-click launcher that pins ``HERMES_DESKTOP_HERMES_ROOT`` to this
     repo so the shell always uses your fork's Python agent, not a managed install.

Double-click on Windows: use ``build_desktop.bat`` (keeps the console open).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DESKTOP_DIR = REPO_ROOT / "apps" / "desktop"
RELEASE_DIR = DESKTOP_DIR / "release"
#: The interpreter PM provisions this checkout against (``.python-version``), e.g. "3.14".
PINNED_PYTHON_FILE = REPO_ROOT / ".python-version"


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str, exit_code: int = 1) -> None:
    log(f"ERROR: {message}")
    raise SystemExit(exit_code)


def configure_stdio() -> None:
    """Prefer UTF-8 on Windows consoles so Chinese paths/logs render cleanly."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Force-build Hermes Desktop from this repo for local self-use.",
    )
    parser.add_argument(
        "--skip-npm-install",
        action="store_true",
        help="Skip root workspace npm install (only applies to the npm fallback path).",
    )
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="Allow hermes content-stamp skip (default always force rebuild).",
    )
    parser.add_argument(
        "--launch",
        action="store_true",
        help="Launch the built app after a successful pack.",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not pause at exit (for terminals / automation).",
    )
    parser.add_argument(
        "--electron-mirror",
        default=os.environ.get("ELECTRON_MIRROR", "").strip() or None,
        help="Optional Electron download mirror base URL (sets ELECTRON_MIRROR).",
    )
    parser.add_argument(
        "--provision",
        action="store_true",
        help="Sync a stale checkout environment (hermes_cli.venv_sync) instead of refusing to pack.",
    )
    parser.add_argument(
        "--shortcut-only",
        action="store_true",
        help="Skip pack; only rewrite launchers + Start Menu shortcut for the existing exe.",
    )
    parser.add_argument(
        "--no-start-menu",
        action="store_true",
        help="Do not install/update the Start Menu shortcut.",
    )
    parser.add_argument(
        "--shortcut-name",
        default=None,
        help='Start Menu shortcut display name (default: "Hermes").',
    )
    return parser.parse_args(argv)


def candidate_python_interpreters() -> list[Path]:
    """Prefer checkout / managed venvs over a bare system Python."""
    candidates: list[Path] = []
    # A developer override wins everywhere else (Desktop, no-console-git): pack
    # against the same interpreter instead of a checkout venv it overrides.
    for env_name in ("HERMES_DESKTOP_PYTHON", "HERMES_PYTHON"):
        override = os.environ.get(env_name, "").strip()
        if override:
            candidates.append(Path(override))
    if sys.platform == "win32":
        candidates.extend(
            [
                REPO_ROOT / ".venv" / "Scripts" / "python.exe",
                REPO_ROOT / "venv" / "Scripts" / "python.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent" / "venv" / "Scripts" / "python.exe",
                Path(os.environ.get("USERPROFILE", "")) / ".hermes" / "hermes-agent" / "venv" / "Scripts" / "python.exe",
            ]
        )
    else:
        candidates.extend(
            [
                REPO_ROOT / ".venv" / "bin" / "python",
                REPO_ROOT / "venv" / "bin" / "python",
                Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python",
            ]
        )
    candidates.append(Path(sys.executable))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or not str(candidate):
            continue
        resolved = str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            unique.append(candidate)
    return unique


def hermes_cli_available(python_executable: Path) -> bool:
    probe = subprocess.run(
        [
            str(python_executable),
            "-c",
            "import hermes_cli.main; print('ok')",
        ],
        cwd=str(REPO_ROOT),
        env=build_python_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0 and "ok" in (probe.stdout or "")


def resolve_build_python() -> Path | None:
    for python_executable in candidate_python_interpreters():
        if hermes_cli_available(python_executable):
            return python_executable
    return None


def build_python_env() -> dict[str, str]:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not existing_pythonpath
        else f"{REPO_ROOT}{os.pathsep}{existing_pythonpath}"
    )
    # Local fork builds must not hang on code-signing identity discovery.
    environment.setdefault("CSC_IDENTITY_AUTO_DISCOVERY", "false")
    return environment


def resolve_source_python() -> Path | None:
    """The interpreter the packaged app resolves for this checkout.

    Mirrors ``apps/desktop/electron/source-python.ts``: an explicit
    ``HERMES_DESKTOP_PYTHON`` override, else the checkout's own virtualenv. The
    launcher this script writes pins ``HERMES_DESKTOP_HERMES_ROOT``, so this is
    the interpreter the app's backend runs (and the one that must be current).
    """
    override = os.environ.get("HERMES_DESKTOP_PYTHON", "").strip()
    if override and Path(override).is_file():
        return Path(override)
    candidates = (
        (Path(".venv") / "Scripts" / "python.exe", Path("venv") / "Scripts" / "python.exe")
        if sys.platform == "win32"
        else (Path(".venv") / "bin" / "python", Path("venv") / "bin" / "python")
    )
    for relative in candidates:
        path = REPO_ROOT / relative
        if path.is_file():
            return path
    return None


def pinned_python_version() -> str | None:
    """``"3.14"`` from the checkout's ``.python-version``; None when unreadable."""
    try:
        value = PINNED_PYTHON_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def interpreter_version(python_executable: Path) -> str | None:
    probe = subprocess.run(
        [str(python_executable), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
        cwd=str(REPO_ROOT),
        env=build_python_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    version = (probe.stdout or "").strip()
    return version if probe.returncode == 0 and version else None


def dependency_environment_state(python_executable: Path) -> tuple[str | None, str]:
    """PM's verdict for this checkout's dependency environment, plus its detail.

    ``hermes_cli.venv_sync --check`` reports ``current`` / ``would-sync``. A probe
    that cannot run at all (older checkout, restricted shell) returns ``(None, detail)``
    so it never blocks a pack on its own — the version pin still does.
    """
    probe = subprocess.run(
        [str(python_executable), "-m", "hermes_cli.venv_sync", "--check", "--json"],
        cwd=str(REPO_ROOT),
        env=build_python_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        result = json.loads((probe.stdout or "").strip().splitlines()[-1])
        return str(result.get("state") or ""), str(result.get("detail") or "")
    except (ValueError, IndexError, AttributeError):
        tail = (probe.stderr or probe.stdout or "").strip().splitlines()
        return None, tail[-1] if tail else ""


def environment_problems(python_executable: Path) -> list[str]:
    """Why this interpreter must not ship: wrong Python, or a stale dependency set.

    Catches the real failure this check exists for: a checkout ``.venv`` created
    before PM pinned the interpreter (3.11 while ``.python-version`` says 3.14)
    passes the ``import hermes_cli.main`` probe while missing every dependency the
    pin gates — the packed app then dies on its first turn.
    """
    problems: list[str] = []
    pinned, actual = pinned_python_version(), interpreter_version(python_executable)
    if pinned and actual and actual != pinned:
        problems.append(f"Python {actual}, but this checkout pins {pinned}")
    state, detail = dependency_environment_state(python_executable)
    if state == "would-sync":
        problems.append("dependency environment is stale (PM reports would-sync)")
    elif state not in (None, "current"):
        log(f"  note: dependency check reported {state!r} ({detail}) — continuing")
    return problems


def provision_dependencies(python_executable: Path) -> None:
    """Run PM's dependency transaction so this checkout's environment is current."""
    run_command(
        [str(python_executable), "-m", "hermes_cli.venv_sync"],
        cwd=REPO_ROOT,
        env=build_python_env(),
        label="hermes_cli.venv_sync (provision dependencies)",
    )


def build_npm_env(electron_mirror: str | None) -> dict[str, str]:
    environment = os.environ.copy()
    environment["CSC_IDENTITY_AUTO_DISCOVERY"] = "false"
    if electron_mirror:
        environment["ELECTRON_MIRROR"] = electron_mirror
    return environment


def resolve_npm() -> str:
    npm_path = shutil.which("npm")
    if not npm_path:
        fail(
            "npm not found on PATH. Install Node.js >= 22.22, then re-run this script."
        )
    return npm_path


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    label: str,
) -> None:
    log(f"→ {label}")
    log(f"  $ {' '.join(command)}")
    log(f"  cwd: {cwd}")
    started_at = time.time()
    result = subprocess.run(command, cwd=str(cwd), env=env, check=False)
    elapsed_seconds = time.time() - started_at
    if result.returncode != 0:
        fail(f"{label} failed (exit {result.returncode}) after {elapsed_seconds:.1f}s")
    log(f"✓ {label} ({elapsed_seconds:.1f}s)")


def packaged_executable_candidates() -> list[Path]:
    if sys.platform == "darwin":
        return list(RELEASE_DIR.glob("mac*/Hermes.app/Contents/MacOS/Hermes"))
    if sys.platform == "win32":
        return [
            RELEASE_DIR / "win-unpacked" / "Hermes.exe",
            RELEASE_DIR / "win-ia32-unpacked" / "Hermes.exe",
            RELEASE_DIR / "win-arm64-unpacked" / "Hermes.exe",
        ]
    return [
        RELEASE_DIR / "linux-unpacked" / "hermes",
        RELEASE_DIR / "linux-unpacked" / "Hermes",
        RELEASE_DIR / "linux-arm64-unpacked" / "hermes",
        RELEASE_DIR / "linux-arm64-unpacked" / "Hermes",
    ]


def find_packaged_executable() -> Path | None:
    existing = [path for path in packaged_executable_candidates() if path.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def build_via_hermes_cli(python_executable: Path, *, force_build: bool, electron_mirror: str | None) -> None:
    command = [
        str(python_executable),
        "-m",
        "hermes_cli.main",
        "desktop",
        "--build-only",
        "--hermes-root",
        str(REPO_ROOT),
        "--ignore-existing",
    ]
    if force_build:
        command.append("--force-build")

    environment = build_python_env()
    if electron_mirror:
        environment["ELECTRON_MIRROR"] = electron_mirror

    run_command(
        command,
        cwd=REPO_ROOT,
        env=environment,
        label="hermes desktop --build-only (official pack path)",
    )


def build_via_npm(*, skip_npm_install: bool, electron_mirror: str | None) -> None:
    if not (DESKTOP_DIR / "package.json").is_file():
        fail(f"Desktop package.json missing: {DESKTOP_DIR / 'package.json'}")

    npm = resolve_npm()
    environment = build_npm_env(electron_mirror)

    if not skip_npm_install:
        run_command(
            [npm, "install"],
            cwd=REPO_ROOT,
            env=environment,
            label="npm install (workspace root)",
        )
    else:
        log("→ Skipping npm install (--skip-npm-install)")

    if sys.platform == "win32":
        log("NOTE: Close any running Hermes Desktop window first, or pack may fail with Access is denied.")

    run_command(
        [npm, "run", "pack"],
        cwd=DESKTOP_DIR,
        env=environment,
        label="npm run pack (unpacked Electron app)",
    )


def default_shortcut_name() -> str:
    # Self-use fork only: no branch/official suffix — user will not install stock Hermes.
    return "Hermes"


def vbs_string_literal(value: str) -> str:
    """Escape a path/string for use inside a VBScript double-quoted literal."""
    return value.replace('"', '""')


def write_windows_launchers(executable: Path) -> dict[str, Path]:
    """Write bat + silent VBS launchers that pin HERMES_DESKTOP_HERMES_ROOT."""
    bat_path = SCRIPT_DIR / "run_hermes_desktop.bat"
    bat_content = f"""@echo off
REM Auto-generated by build_desktop.py — do not hand-edit unless you know why.
set "HERMES_DESKTOP_HERMES_ROOT={REPO_ROOT}"
set "HERMES_DESKTOP_IGNORE_EXISTING=1"
start "" "{executable}"
"""
    bat_path.write_text(bat_content, encoding="utf-8", newline="\r\n")

    # VBS: no console flash; Start Menu .lnk should point here.
    # shell.Run first arg must be a quoted command string when the path has spaces:
    #   shell.Run """C:\path with spaces\Hermes.exe""", 1, False
    # Build that line outside an f-triple-quote so Python string delimiters stay unambiguous.
    vbs_path = SCRIPT_DIR / "run_hermes_desktop.vbs"
    repo_root_literal = vbs_string_literal(str(REPO_ROOT))
    workdir_literal = vbs_string_literal(str(executable.parent))
    exe_literal = vbs_string_literal(str(executable))
    vbs_run_line = 'shell.Run """' + exe_literal + '""", 1, False'
    vbs_content = "\r\n".join(
        [
            "' Auto-generated by build_desktop.py — do not hand-edit unless you know why.",
            "Option Explicit",
            "Dim shell, processEnvironment",
            'Set shell = CreateObject("WScript.Shell")',
            'Set processEnvironment = shell.Environment("PROCESS")',
            f'processEnvironment("HERMES_DESKTOP_HERMES_ROOT") = "{repo_root_literal}"',
            'processEnvironment("HERMES_DESKTOP_IGNORE_EXISTING") = "1"',
            f'shell.CurrentDirectory = "{workdir_literal}"',
            vbs_run_line,
            "",
        ]
    )
    vbs_path.write_text(vbs_content, encoding="utf-8", newline="\r\n")
    return {"bat": bat_path, "vbs": vbs_path}


def write_unix_launcher(executable: Path) -> Path:
    launcher_path = SCRIPT_DIR / "run_hermes_desktop.sh"
    content = f"""#!/usr/bin/env bash
# Auto-generated by build_desktop.py — do not hand-edit unless you know why.
set -euo pipefail
export HERMES_DESKTOP_HERMES_ROOT="{REPO_ROOT}"
export HERMES_DESKTOP_IGNORE_EXISTING=1
exec "{executable}" "$@"
"""
    launcher_path.write_text(content, encoding="utf-8")
    try:
        launcher_path.chmod(launcher_path.stat().st_mode | 0o111)
    except OSError:
        pass
    return launcher_path


def powershell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def install_windows_start_menu_shortcut(
    executable: Path,
    vbs_launcher: Path,
    *,
    shortcut_name: str,
) -> Path:
    """Install a Start Menu .lnk that runs the VBS launcher (env-pinned).

    Windows .lnk files cannot carry arbitrary environment variables, so the
    shortcut targets the VBS wrapper which sets HERMES_DESKTOP_* then starts
    Hermes.exe. Placing the .lnk under the user Start Menu Programs folder
    makes it show up under Start → All apps (right-click → Pin to Start if
    you also want a Start tile).
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        fail("APPDATA is not set; cannot install Start Menu shortcut.")

    programs_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    shortcut_path = programs_dir / f"{shortcut_name}.lnk"

    # Drop older self-use names like "Hermes (my-feature).lnk" so Start Menu
    # only shows the bare "Hermes" entry.
    for stale_shortcut in programs_dir.glob("Hermes (*).lnk"):
        if stale_shortcut.resolve() == shortcut_path.resolve():
            continue
        try:
            stale_shortcut.unlink()
            log(f"  removed stale shortcut: {stale_shortcut.name}")
        except OSError as remove_error:
            log(f"  warning: could not remove {stale_shortcut.name}: {remove_error}")

    description = f"Hermes Desktop bound to {REPO_ROOT}"
    powershell_script = f"""
$ErrorActionPreference = 'Stop'
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut({powershell_single_quote(str(shortcut_path))})
$Shortcut.TargetPath = {powershell_single_quote(str(vbs_launcher))}
$Shortcut.WorkingDirectory = {powershell_single_quote(str(executable.parent))}
$Shortcut.IconLocation = {powershell_single_quote(f"{executable},0")}
$Shortcut.Description = {powershell_single_quote(description)}
$Shortcut.WindowStyle = 1
$Shortcut.Save()
Write-Output $Shortcut.FullName
"""
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            powershell_script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        fail(f"Start Menu shortcut install failed: {detail or f'exit {result.returncode}'}")

    if not shortcut_path.is_file():
        fail(f"Start Menu shortcut was not created: {shortcut_path}")
    return shortcut_path


def write_launchers(executable: Path) -> dict[str, Path] | Path:
    if sys.platform == "win32":
        return write_windows_launchers(executable)
    return write_unix_launcher(executable)


def launch_app(executable: Path) -> None:
    environment = os.environ.copy()
    environment["HERMES_DESKTOP_HERMES_ROOT"] = str(REPO_ROOT)
    environment["HERMES_DESKTOP_IGNORE_EXISTING"] = "1"

    log(f"→ Launching {executable}")
    if sys.platform == "win32":
        # Detach so closing this console does not kill the app.
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            env=environment,
            creationflags=creationflags,
            close_fds=True,
        )
    else:
        subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            env=environment,
            start_new_session=True,
            close_fds=True,
        )
    log("✓ Launch requested (app runs detached)")


def pause_for_double_click(*, enabled: bool) -> None:
    if not enabled:
        return
    if sys.platform != "win32":
        return
    try:
        input("\n按 Enter 关闭窗口…")
    except EOFError:
        time.sleep(3)


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(argv)
    force_build = not args.no_force
    shortcut_name = args.shortcut_name or default_shortcut_name()

    log("=" * 60)
    log("Hermes Desktop local pack (path A)")
    log(f"  repo root : {REPO_ROOT}")
    log(f"  desktop   : {DESKTOP_DIR}")
    log(f"  force     : {force_build}")
    log(f"  mode      : {'shortcut-only' if args.shortcut_only else 'full pack'}")
    log("=" * 60)

    if not (REPO_ROOT / "apps" / "desktop" / "package.json").is_file():
        fail(f"Not a hermes-agent checkout (missing apps/desktop): {REPO_ROOT}")

    if not args.shortcut_only:
        # The launcher pins HERMES_DESKTOP_HERMES_ROOT, so the app spawns THIS
        # checkout's interpreter: validate that one before packing a broken app.
        source_python = resolve_source_python()
        if source_python is not None:
            log(f"App interpreter : {source_python}")
            problems = environment_problems(source_python)
            if problems:
                for problem in problems:
                    log(f"  ! {problem}")
                if args.provision:
                    provision_dependencies(source_python)
                else:
                    fail(
                        "refusing to pack — the app would spawn this checkout's interpreter and its "
                        "environment is incomplete.\n"
                        "  fix: run  .\\activate.ps1  (or  hermes pm install ), then re-run this script;\n"
                        "       or re-run with --provision to sync it here.",
                        exit_code=2,
                    )
        else:
            log(
                "WARN: no checkout interpreter (.venv/venv or HERMES_DESKTOP_PYTHON); the app will "
                "fall back to an installed runtime."
            )

        build_python = resolve_build_python()
        if build_python is not None:
            log(f"Using hermes_cli via: {build_python}")
            build_via_hermes_cli(
                build_python,
                force_build=force_build,
                electron_mirror=args.electron_mirror,
            )
        else:
            log("hermes_cli not importable from known Pythons — falling back to npm pack.")
            log("Tip: activate the repo venv (or managed ~/.hermes venv) for the full official path.")
            build_via_npm(
                skip_npm_install=args.skip_npm_install,
                electron_mirror=args.electron_mirror,
            )

    executable = find_packaged_executable()
    if executable is None:
        if args.shortcut_only:
            fail(
                f"No packaged app under {RELEASE_DIR}. "
                "Run a full pack first (build_desktop.bat without --shortcut-only)."
            )
        fail(
            f"Pack finished but no executable under {RELEASE_DIR}. "
            "Check the npm/electron-builder log above."
        )

    launcher_paths = write_launchers(executable)
    start_menu_shortcut: Path | None = None

    if sys.platform == "win32":
        assert isinstance(launcher_paths, dict)
        if not args.no_start_menu:
            log(f"→ Installing Start Menu shortcut: {shortcut_name}")
            start_menu_shortcut = install_windows_start_menu_shortcut(
                executable,
                launcher_paths["vbs"],
                shortcut_name=shortcut_name,
            )
            log(f"✓ Start Menu shortcut: {start_menu_shortcut}")
    else:
        assert isinstance(launcher_paths, Path)

    log("")
    log("=" * 60)
    log("OK" if args.shortcut_only else "BUILD OK")
    log(f"  app       : {executable}")
    if isinstance(launcher_paths, dict):
        log(f"  bat       : {launcher_paths['bat']}")
        log(f"  vbs       : {launcher_paths['vbs']}")
    else:
        log(f"  launcher  : {launcher_paths}")
    if start_menu_shortcut is not None:
        log(f"  start menu: {start_menu_shortcut}")
        log("  tip       : Start → search shortcut name → right-click → 固定到开始屏幕")
    log("  env pin   : HERMES_DESKTOP_HERMES_ROOT → this repo")
    log("  env pin   : HERMES_DESKTOP_IGNORE_EXISTING=1")
    log("=" * 60)
    if start_menu_shortcut is not None:
        log("Open from Start Menu (env already baked into the shortcut chain).")
    else:
        log("Next: use the launcher, or re-run with --launch.")

    if args.launch:
        launch_app(executable)

    pause_for_double_click(enabled=not args.no_pause)
    return 0


if __name__ == "__main__":
    exit_code = 1
    want_pause = "--no-pause" not in sys.argv
    try:
        exit_code = main()
    except SystemExit as system_exit:
        code = system_exit.code
        if code is None:
            exit_code = 0
        elif isinstance(code, int):
            exit_code = code
        else:
            exit_code = 1
            log(str(code))
    except KeyboardInterrupt:
        log("\nInterrupted.")
        exit_code = 130
    except Exception as unexpected_error:
        log(f"ERROR: unexpected failure: {unexpected_error}")
        exit_code = 1
    finally:
        # main() already pauses on success; only pause here on failure paths
        # where main() never reached its own pause.
        if want_pause and exit_code not in (0, None) and sys.platform == "win32":
            try:
                input("\n构建失败。按 Enter 关闭窗口…")
            except EOFError:
                time.sleep(3)
    raise SystemExit(exit_code)
