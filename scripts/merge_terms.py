#!/usr/bin/env python3
"""Merge new_terms from chunk REPORT lines into the terminology seed.

Subagents report `new_terms=English→中文, ...` in their REPORT line; this
script aggregates them, deduplicates against the existing seed, and appends
new rows so later sections inherit the vocabulary. Run it after each
section completes, before dispatching the next.

Usage:
  uv run merge_terms.py --config reader.config.json
"""

from __future__ import annotations

import argparse
import re
import sys

from readerlib import load_config, load_manifest, resolve, root

REPORT_RE = re.compile(r"^REPORT:\s*(.*)$", re.MULTILINE)


def report_terms(text: str) -> list[tuple[str, str]]:
    """(english, chinese) pairs from the REPORT line's new_terms field."""
    m = REPORT_RE.search(text)
    if not m:
        return []
    field = ""
    for part in m.group(1).split(";"):
        part = part.strip()
        if part.startswith("new_terms="):
            field = part[len("new_terms="):]
            break
    pairs = []
    for item in field.split(","):
        item = item.strip()
        if "→" not in item:
            continue
        en, _, zh = item.partition("→")
        en, zh = en.strip(), zh.strip()
        if en and zh and en.lower() not in ("none", "无", "-"):
            pairs.append((en, zh))
    return pairs


def existing_terms(seed_path) -> set[str]:
    if not seed_path or not seed_path.exists():
        return set()
    out = set()
    for line in seed_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and cells[0] and cells[0].lower() != "english":
                out.add(cells[0].lower())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
    _manifest, chunks = load_manifest(cfg, strict=False)

    collected: list[tuple[str, str, str]] = []
    for ch in chunks:
        if ch.get("kind", "translate") != "translate":
            continue
        fp = root(cfg) / ch["file"]
        if not fp.exists():
            continue
        for en, zh in report_terms(fp.read_text(encoding="utf-8")):
            collected.append((en, zh, ch["id"]))

    seed = resolve(cfg, "pipeline.glossary", "tmp/terminology-seed.md")
    known = existing_terms(seed)
    if seed and not seed.exists():
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text("# Terminology seed\n\n| English | 中文 | 备注 |\n|---|---|---|\n",
                        encoding="utf-8")

    added = 0
    lines = []
    for en, zh, cid in collected:
        if en.lower() in known:
            continue
        known.add(en.lower())
        lines.append(f"| {en} | {zh} | 来自 {cid} |")
        added += 1
    if added and seed:
        with seed.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(f"terms: {len(collected)} reported, {added} new -> {seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
