#!/usr/bin/env python3
"""Parse a PDF with MinerU, write the markdown dump, figure inventory, and parse meta.

Usage:
  uv run parse_paper.py --pdf paper.pdf --out tmp/mineru_full.md
  uv run parse_paper.py --pdf paper.pdf --out tmp/mineru_full.md --assets reader/assets

Exit codes: 0 ok; 1 parse/IO error; 2 environment (server/permission) error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

LOCATOR_RE = re.compile(r"doc:([0-9a-f]+)/tier:(\w+)/page:(\d+)/block:(\d+)")
PAGE_RE = re.compile(r"<!--\s*page\s+(\d+)\s+of\s+(\d+)")
CAPTION_RE = re.compile(r"^\s*(?:Figure|Fig\.)\s*([0-9]+(?:[.\-][0-9]+)*)[.:]?\s+")
TABLE_RE = re.compile(r"^\s*Table\s*([0-9]+(?:[.\-][0-9]+)*)[.:]?\s+")


def env_error(text: str) -> bool:
    low = text.lower()
    return ("winerror 5" in low or "拒绝访问" in text or "permission" in low
            or "not running" in low or "server start" in low or "找不到" in text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf")
    ap.add_argument("--from-md")
    ap.add_argument("--out", default="tmp/mineru_full.md")
    ap.add_argument("--assets")
    ap.add_argument("--meta", default="tmp/parse_meta.json")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not args.pdf and not args.from_md:
        print("ERROR: pass --pdf or --from-md", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.from_md:
        src_md = Path(args.from_md)
        if not src_md.exists():
            print(f"ERROR: {src_md} not found", file=sys.stderr)
            return 1
        md = src_md.read_text(encoding="utf-8")
        pdf = Path(args.pdf) if args.pdf else None
    else:
        mineru = shutil.which("mineru")
        if not mineru:
            print("ERROR: mineru not found in PATH", file=sys.stderr)
            return 2
        pdf = Path(args.pdf)
        if not pdf.exists():
            print(f"ERROR: {pdf} not found", file=sys.stderr)
            return 1
        proc = subprocess.run(
            [mineru, "parse", str(pdf), "--pages", "all", "--output", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            text = (proc.stdout or "") + (proc.stderr or "")
            print(text[-2000:], file=sys.stderr)
            if env_error(text):
                print("\nFIX: run preflight.py, then `mineru server start` "
                      "(it needs ~/.mineru write access; use danger-full-access).",
                      file=sys.stderr)
                return 2
            return 1
        md = out.read_text(encoding="utf-8")

    lines = md.splitlines()
    page_max = 0
    page_total = 0
    for line in lines:
        m = PAGE_RE.search(line)
        if m:
            page_max = max(page_max, int(m.group(1)))
            page_total = max(page_total, int(m.group(2)))

    locators = []
    seen: set[str] = set()
    for lineno, line in enumerate(lines, 1):
        for m in LOCATOR_RE.finditer(line):
            loc = m.group(0)
            if loc in seen:
                continue
            seen.add(loc)
            locators.append({"locator": loc, "doc": m.group(1), "tier": m.group(2),
                             "page": int(m.group(3)), "block": int(m.group(4)),
                             "line": lineno})

    figures = []
    for item in locators:
        name = f"fig-p{item['page']}-b{item['block']}"
        caption_line = None
        for j in range(item["line"], min(item["line"] + 12, len(lines) + 1)):
            if CAPTION_RE.match(lines[j - 1]) or TABLE_RE.match(lines[j - 1]):
                caption_line = j
                break
        figures.append({**item, "suggested_name": name,
                        "caption_line": caption_line,
                        "figure_number": None,
                        "image": f"assets/{name}.png" if args.assets else None})
    fig_path = out.parent / "figures.json"
    fig_path.write_text(json.dumps({"figures": figures}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")

    image_errors = 0
    if args.assets:
        assets = Path(args.assets)
        assets.mkdir(parents=True, exist_ok=True)
        for item in figures:
            target = assets / f"fig-p{item['page']}-b{item['block']}.png"
            if target.exists() and not args.force:
                continue
            read = subprocess.run(
                [mineru, "read", item["locator"], "--format", "image", "--output", str(target)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if read.returncode != 0:
                image_errors += 1

    doc_id = locators[0]["doc"] if locators else ""
    tier = locators[0]["tier"] if locators else ""
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest() if pdf else ""
    meta = {
        "source_pdf": pdf.name if pdf else "",
        "source_sha256": sha,
        "doc": doc_id,
        "tier": tier,
        "pages": page_total or page_max,
        "md_lines": len(lines),
        "image_blocks": len(figures),
        "figures_with_caption": sum(1 for f in figures if f["caption_line"]),
        "image_errors": image_errors,
    }
    meta_path = Path(args.meta)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")
    print(f"doc={doc_id} tier={tier} pages={meta['pages']} "
          f"image_blocks={len(figures)} figures_with_caption={meta['figures_with_caption']} "
          f"lines={len(lines)} -> {out}")
    if image_errors:
        print(f"WARN: {image_errors} image extraction(s) failed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
