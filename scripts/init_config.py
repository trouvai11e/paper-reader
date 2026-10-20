#!/usr/bin/env python3
"""Create reader.config.json from the example, fill paper metadata, and prepare reader/.

Usage:
  uv run init_config.py --pdf paper.pdf --title "..." --authors "..." \
      --doi "10.xxxx/xxxx" --out reader.config.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from readerlib import resolve_template

EXAMPLE = Path(__file__).resolve().parent.parent / "references" / "config.example.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf")
    ap.add_argument("--out", default="reader.config.json")
    ap.add_argument("--template", default="TeXTemplate/elegantnote.cls")
    ap.add_argument("--example", default=str(EXAMPLE))
    ap.add_argument("--title")
    ap.add_argument("--title-tex")
    ap.add_argument("--title-zh")
    ap.add_argument("--authors")
    ap.add_argument("--authors-zh")
    ap.add_argument("--venue")
    ap.add_argument("--venue-line")
    ap.add_argument("--doi")
    ap.add_argument("--msc")
    ap.add_argument("--keywords")
    ap.add_argument("--year", type=int)
    ap.add_argument("--pages", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"ERROR: {out} exists; use --force to overwrite", file=sys.stderr)
        return 1
    example = Path(args.example)
    if not example.exists():
        print(f"ERROR: example config not found: {example}", file=sys.stderr)
        return 1
    cfg = json.loads(example.read_text(encoding="utf-8"))
    paper = cfg.setdefault("paper", {})

    if args.pdf:
        paper["source_pdf"] = Path(args.pdf).name
    # Start from a blank paper block so example placeholders do not leak.
    paper.update({
        "title": args.title or "",
        "title_tex": args.title_tex or args.title or "",
        "title_zh": args.title_zh or "",
        "authors": args.authors or "",
        "authors_zh": args.authors_zh or "",
        "venue": args.venue or "",
        "venue_line": args.venue_line or "",
        "doi": args.doi or "",
        "msc": args.msc or "",
        "keywords": args.keywords or "",
        "year": args.year or paper.get("year", 0),
        "pages": args.pages or paper.get("pages", 0),
        "mineru_parse_id": "PENDING",
        "reading_notes": [],
    })
    if not paper["venue_line"] and paper["venue"]:
        doi = paper.get("doi", "")
        paper["venue_line"] = f"{paper['venue']}. DOI: {doi}." if doi else paper["venue"]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    reader = out.parent / cfg.get("pipeline", {}).get("output_dir", "reader")
    reader.mkdir(parents=True, exist_ok=True)
    cls_src = resolve_template(args.template, base=out.parent)
    if cls_src.exists() and not (reader / "elegantnote.cls").exists():
        shutil.copy2(cls_src, reader / "elegantnote.cls")

    print(f"wrote {out}")
    print("next:")
    print("  uv run scripts/preflight.py --template TeXTemplate/elegantnote.cls")
    print("  uv run scripts/parse_paper.py --pdf <pdf> --out tmp/mineru_full.md --assets reader/assets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
