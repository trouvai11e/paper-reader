#!/usr/bin/env python3
"""Generate references chunk files deterministically from the MinerU dump.

Reference entries are kept in English (chunk-format rule); no LLM is
involved. The generator merges wrapped lines into entries, renumbers them
sequentially, cleans OCR spacing noise, and writes a chunk file per
manifest chunk with `kind: "references"` plus a REPORT line so the chunk
state machine marks it done.

Suspicious lines (unparseable entry starts, entries that look truncated)
are listed in UNCERTAINTIES instead of being guessed at.

Usage:
  uv run gen_references.py --config reader.config.json --mineru tmp/mineru_full.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from readerlib import (
    load_config,
    load_inventory,
    load_manifest,
    root,
)

ENTRY_START_RE = re.compile(r"^\s*(?:\[(\d+)\]|(\d+)[.)])\s*(.*)$")
PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+\d+\s*-->")
PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}\s*$")
REF_HEAD_RE = re.compile(r"^\s*(?:#{1,4}\s*)?(?:\d+(?:\.\d+)*\.?\s*)?"
                         r"(?:references?|参考文献)\s*[.:]?\s*$", re.IGNORECASE)
DOI_GAP_RE = re.compile(r"(doi[:\s]*10\.)\s+(\d)", re.IGNORECASE)
RUNNING_HEAD_RE = re.compile(r"^\s*\d{1,4}\s+[A-Z][A-Z .'-]{6,}\s*$")


def clean_line(line: str) -> str:
    """Collapse OCR spacing noise without touching content."""
    line = PAGE_MARKER_RE.sub("", line)
    line = re.sub(r"\s+", " ", line).strip()
    line = DOI_GAP_RE.sub(r"\1\2", line)
    return line


def parse_entries(lines: list[str], start: int, end: int) -> tuple[list[str], list[str], int]:
    """Turn the dump range [start, end] (1-based inclusive) into entries.

    Returns (entries, uncertainties, boilerplate_lines_dropped). A new entry
    starts at a `[n]` / `n.` / `n)` marker; other lines continue the current
    entry. Boilerplate (page numbers, running heads, the section heading) is
    dropped and counted.
    """
    entries: list[str] = []
    uncertainties: list[str] = []
    dropped = 0
    for i in range(start, end + 1):
        raw = clean_line(lines[i - 1])
        if not raw:
            continue
        if PAGE_NUM_RE.match(raw) or RUNNING_HEAD_RE.match(raw) or REF_HEAD_RE.match(raw):
            dropped += 1
            continue
        m = ENTRY_START_RE.match(raw)
        if m:
            entries.append(m.group(3).strip())
        elif entries:
            entries[-1] += " " + raw
        else:
            entries.append(raw)
            uncertainties.append(
                f"line {i}: text before the first entry marker; kept as entry 1")
    for idx, entry in enumerate(entries, 1):
        if len(entry) < 15:
            uncertainties.append(f"entry {idx}: only {len(entry)} chars; check the source page")
    return entries, uncertainties, dropped


def references_title(inventory: dict) -> str:
    """Bilingual references heading, keeping the paper's number if numbered."""
    for h in inventory.get("headings", []):
        text = f"{h.get('en', '')} {h.get('zh', '')}"
        if re.search(r"references?|参考文献", text, re.IGNORECASE):
            num = str(h.get("num") or "").strip()
            if num and num[0].isdigit():
                return f"## {num}. 参考文献（References）"
    return "## 参考文献（References）"


def render_chunk(title: str, entries: list[str], uncertainties: list[str],
                 dropped: int) -> str:
    lines = [
        title,
        "",
        "条目保留英文原文，按原顺序编号。",
        "",
    ]
    lines += [f"{i}. {entry}" for i, entry in enumerate(entries, 1)]
    lines += [
        "",
        "UNCERTAINTIES:",
    ]
    lines += [f"- {u}" for u in uncertainties] or ["- (none)"]
    lines += [
        "",
        (f"REPORT: S=0 E=0 C=0 F=0 T=0; refs={len(entries)}; "
         f"boilerplate_lines_dropped={dropped}; uncertainties={len(uncertainties)}"),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--mineru", required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
    mineru = Path(args.mineru)
    if not mineru.is_absolute():
        mineru = root(cfg) / mineru
    lines = mineru.read_text(encoding="utf-8").splitlines()
    _manifest, chunks = load_manifest(cfg, strict=False)
    refs = [c for c in chunks if c.get("kind") == "references"]
    if not refs:
        print("no references chunks in manifest; nothing to do")
        return 0
    inventory = load_inventory(cfg)
    title = references_title(inventory)
    for ch in refs:
        entries, uncertainties, dropped = parse_entries(
            lines, ch["line_start"], ch["line_end"])
        fp = root(cfg) / ch["file"]
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(render_chunk(title, entries, uncertainties, dropped),
                      encoding="utf-8")
        print(f"{ch['id']}: {len(entries)} entries, "
              f"{len(uncertainties)} uncertainties -> {ch['file']}")
    print("run `chunk_state.py --config <config> sync` to record the state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
