#!/usr/bin/env python3
"""Build a table/figure inventory from a MinerU markdown dump.

Usage:
  uv run inventory.py --mineru tmp/mineru_full.md --out tmp/inventory.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from readerlib import caption_inventory


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineru", required=True)
    ap.add_argument("--out", default="tmp/inventory.json")
    args = ap.parse_args()
    text = Path(args.mineru).read_text(encoding="utf-8")
    items = caption_inventory(text)
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for item in items:
        key = (item["kind"], item["num"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    data = {"items": unique}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tables = sum(1 for i in unique if i["kind"] == "table")
    figs = len(unique) - tables
    print(f"inventory: {tables} tables, {figs} figures -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
