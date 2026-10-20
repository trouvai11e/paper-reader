#!/usr/bin/env python3
"""Rebuild reader.tex from the committed reader/paper.md (no LLM needed).

Usage: uv run md2tex.py --config reader.config.json
"""

from __future__ import annotations

import argparse
import sys

from readerlib import cut_body, load_config, md_to_tex, out_dir, render_document


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
    out = out_dir(cfg)
    paper_md = out / "paper.md"
    if not paper_md.exists():
        print(f"ERROR: {paper_md} not found; run assemble.py first", file=sys.stderr)
        return 1
    body = cut_body(paper_md.read_text(encoding="utf-8"))
    tex = render_document(md_to_tex(body, cfg), cfg)
    (out / "reader.tex").write_text(tex, encoding="utf-8")
    print(f"wrote {out / 'reader.tex'} ({len(tex.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
