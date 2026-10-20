#!/usr/bin/env python3
"""List accent commands in paper.md with their block ids, for a human spot-check.

OCR often adds or drops dots/hats/bars. An automated diff against the PDF is too
noisy, so this script produces the review list and the agent checks the cited
pages.

Usage:
  uv run accent_audit.py --paper reader/paper.md [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ACCENT_RE = re.compile(
    r"\\(dot|hat|bar|tilde|widehat|overline|underline|check|acute|grave)\b")
ANCHOR_RE = re.compile(r'<a id="([SETF]\d+)"></a>')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", default="reader/paper.md")
    ap.add_argument("--json")
    args = ap.parse_args()
    lines = Path(args.paper).read_text(encoding="utf-8").splitlines()
    current = ""
    page = ""
    rows = []
    for idx, line in enumerate(lines, 1):
        m = ANCHOR_RE.search(line)
        if m:
            current = m.group(1)
        sm = re.search(r"\*\*Source:\*\*\s*p\.([0-9–-]+)", line)
        if sm:
            page = sm.group(1)
        for am in ACCENT_RE.finditer(line):
            start = max(0, am.start() - 40)
            end = min(len(line), am.end() + 40)
            rows.append({
                "block": current, "page": page, "line": idx,
                "command": am.group(0),
                "context": line[start:end].strip(),
            })
    if args.json:
        Path(args.json).write_text(
            json.dumps({"accents": rows}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    for r in rows:
        print(f"{r['block']} p.{r['page']} {r['command']}  {r['context']}")
    print(f"total accents: {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
