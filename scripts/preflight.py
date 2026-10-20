#!/usr/bin/env python3
"""Preflight for a paper-reader project: tools, uv cache, MinerU server, fonts.

Usage:
  uv run preflight.py --template TeXTemplate/elegantnote.cls
  uv run preflight.py --start-server        # also try `mineru server start`

Exit codes: 0 all pass; 1 fixable failure; 2 needs approval / escalation.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from readerlib import resolve_template

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OK, WARN, FAIL = "ok", "warn", "fail"
issues: list[tuple[str, str]] = []
approval_needed = False


def note(kind: str, msg: str, fix: str = "") -> None:
    print(f"[{kind}] {msg}")
    if fix:
        print(f"       fix: {fix}")
    if kind in (WARN, FAIL):
        issues.append((kind, msg))


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def check_tools() -> None:
    required = ["mineru", "xelatex", "pdffonts", "pdfinfo"]
    optional = ["pdftoppm"]
    for name in required:
        path = shutil.which(name)
        note(OK if path else FAIL, f"{name}: {path or 'NOT FOUND'}",
             "" if path else f"install {name} and add it to PATH")
    for name in optional:
        path = shutil.which(name)
        note(OK if path else WARN, f"{name}: {path or 'not found (optional)'}")


def check_uv_cache() -> None:
    env = os.environ.get("UV_CACHE_DIR")
    if not env:
        note(WARN, "UV_CACHE_DIR is not set",
             '$env:UV_CACHE_DIR="$PWD/tmp/uv-cache"  (Windows/PowerShell)')
        return
    p = Path(env)
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".preflight"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        note(OK, f"UV_CACHE_DIR writable: {p}")
    except OSError as exc:
        note(FAIL, f"UV_CACHE_DIR not writable: {p} ({exc})",
             "point UV_CACHE_DIR at a workspace path")


def check_mineru_home() -> None:
    home = Path.home() / ".mineru"
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".preflight"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        note(OK, f"~/.mineru writable: {home}")
    except OSError as exc:
        global approval_needed
        approval_needed = True
        note(FAIL, f"~/.mineru not writable: {home} ({exc})",
             "run MinerU with danger-full-access (it needs ~/.mineru)")


def check_mineru_server(start: bool) -> None:
    exe = shutil.which("mineru")
    if not exe:
        return
    proc = run([exe, "server", "status", "--json"])
    text = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        note(OK, "mineru server: running")
        return
    if "WinError 5" in text or "拒绝访问" in text:
        global approval_needed
        approval_needed = True
        note(FAIL, "mineru server status denied on ~/.mineru",
             "approve danger-full-access for `mineru server start`")
        return
    if "not running" in text.lower() or "找不到" in text or "server start" in text:
        if start:
            started = run([exe, "server", "start"])
            if started.returncode == 0:
                note(OK, f"mineru server started: {started.stdout.strip()}")
                return
            note(FAIL, f"mineru server start failed: {started.stdout.strip()}",
                 "approve danger-full-access for `mineru server start`")
            return
        # Not an error at preflight time: the server only needs to be up for
        # parse_paper. Warn and point at the flag instead of failing.
        note(WARN, "mineru server is not running",
             f"rerun with --start-server, or `{exe} server start` before Phase 1")
        return
    note(FAIL, f"mineru server status failed: {text.strip()[:200]}",
         "run `mineru server start` and retry")


def check_font(template: Path, workdir: Path) -> None:
    xelatex = shutil.which("xelatex")
    pdffonts = shutil.which("pdffonts")
    if not xelatex or not pdffonts:
        return
    if not template.exists():
        note(WARN, f"template not found: {template}", "set --template to elegantnote.cls")
        return
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, workdir / "elegantnote.cls")
    tex = workdir / "fonttest.tex"
    tex.write_text(
        "\\documentclass[cn,normal,blue,12pt,chinesefont=founder]{elegantnote}\n"
        "\\begin{document}\n"
        "\\noindent 方正字体测试：保正有限体积格式。Founder font gate.\n"
        "\\end{document}\n", encoding="utf-8")
    proc = run([xelatex, "-interaction=nonstopmode", "-halt-on-error", "fonttest.tex"],
               cwd=workdir)
    if proc.returncode != 0:
        note(FAIL, "font test failed to compile", "inspect tmp/preflight/fonttest.log")
        return
    fonts = run([pdffonts, str(workdir / "fonttest.pdf")]).stdout
    if "FZ" in fonts:
        note(OK, "font test: FZ fonts embedded")
    else:
        note(FAIL, "font test compiled but no FZ font (ctexfont fallback)",
             "add chinesefont=founder to the class options")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="TeXTemplate/elegantnote.cls")
    ap.add_argument("--workdir", default="tmp/preflight")
    ap.add_argument("--start-server", action="store_true")
    args = ap.parse_args()

    print("== Tools ==")
    check_tools()
    print("== UV cache ==")
    check_uv_cache()
    print("== MinerU ==")
    check_mineru_home()
    check_mineru_server(args.start_server)
    print("== Fonts ==")
    check_font(resolve_template(args.template), Path(args.workdir))

    errors = [m for k, m in issues if k == FAIL]
    warns = [m for k, m in issues if k == WARN]
    if errors:
        print(f"\nFAIL preflight: {len(errors)} error(s), {len(warns)} warning(s)")
        return 2 if approval_needed else 1
    print(f"\nPASS preflight: {len(warns)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
