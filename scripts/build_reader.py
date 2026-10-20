#!/usr/bin/env python3
"""Build reader.pdf: md2tex -> xelatex x2 -> gates (errors, pages, fonts).

Usage: uv run build_reader.py --config reader.config.json
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys

from readerlib import (
    cfg_get,
    cut_body,
    load_config,
    md_to_tex,
    out_dir,
    render_document,
    resolve,
)


def fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--keep-aux", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)
    out = out_dir(cfg)

    paper_md = out / "paper.md"
    if not paper_md.exists():
        return fail(f"{paper_md} not found; run assemble.py first")
    body = cut_body(paper_md.read_text(encoding="utf-8"))
    (out / "reader.tex").write_text(
        render_document(md_to_tex(body, cfg), cfg), encoding="utf-8")

    cls_src = resolve(cfg, "pipeline.template_cls", "TeXTemplate/elegantnote.cls")
    if cls_src and cls_src.exists():
        shutil.copy2(cls_src, out / "elegantnote.cls")
    elif not (out / "elegantnote.cls").exists():
        return fail("elegantnote.cls missing (set pipeline.template_cls)")

    xelatex = shutil.which("xelatex")
    if not xelatex:
        return fail("xelatex not found in PATH")

    for run in (1, 2):
        proc = subprocess.run(
            [xelatex, "-interaction=nonstopmode", "-halt-on-error", "reader.tex"],
            cwd=out, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            log = (out / "reader.log")
            tail = log.read_text(encoding="utf-8", errors="replace")[-3000:] if log.exists() else proc.stdout[-3000:]
            return fail(f"xelatex pass {run} failed\n{tail}")

    log = (out / "reader.log").read_text(encoding="utf-8", errors="replace")
    errors = [ln for ln in log.splitlines() if ln.startswith("!")]
    if errors:
        return fail("LaTeX errors:\n" + "\n".join(errors[:10]))

    m = re.search(r"Output written on .*?\((\d+) pages?\)", log)
    pages = int(m.group(1)) if m else 0
    if pages == 0:
        return fail("could not determine PDF page count from reader.log")

    font = cfg_get(cfg, "layout.chinesefont", "founder")
    if font == "founder":
        pdffonts = shutil.which("pdffonts")
        if pdffonts:
            fonts = subprocess.run([pdffonts, str(out / "reader.pdf")],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace").stdout
            if "FZ" not in fonts:
                return fail("chinesefont=founder requested, but pdffonts shows no FZ font")
        else:
            print("WARN: pdffonts not found; skipped font gate", file=sys.stderr)

    print(f"PASS build: {pages} pages, errors=0, font={font}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
