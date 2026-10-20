#!/usr/bin/env python3
"""Plan chunk line ranges from a MinerU markdown dump.

Density-aware: each chunk is capped by an estimated output size
(`1.1 * text_lines + 3.5 * display_blocks`), not only by input lines.
Splits at `##` sections, then at blank lines / numbered subsections.

Writes tmp/chunk_manifest.json with status/next_line/counts fields for the
chunk state machine.

Usage:
  uv run plan_chunks.py --mineru tmp/mineru_full.md --out tmp/chunk_manifest.json \
      --max-lines 300 --target-out 220 --headings tmp/headings.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

NUM_HEAD_RE = re.compile(r"^\d+(?:\.\d+)+\.\s")
ENV_RE = re.compile(
    r"\\begin\{(equation|align|aligned|gather|multline|cases|array|pmatrix|bmatrix)\}")


def estimate_out(lines: list[str], start: int, end: int) -> int:
    """Estimated reader output lines for [start, end] (1-based inclusive)."""
    text_lines = 0
    eq_blocks = 0
    in_display = False
    for i in range(start - 1, end):
        stripped = lines[i].strip()
        if stripped == "$$":
            if not in_display:
                eq_blocks += 1
            in_display = not in_display
            continue
        text_lines += 1
        if ENV_RE.search(lines[i]):
            eq_blocks += 1
    return int(1.1 * text_lines + 3.5 * eq_blocks)


def split_section(lines: list[str], start: int, end: int,
                  max_lines: int, target_out: int) -> list[tuple[int, int]]:
    """Greedy split with both a hard line cap and an estimated-output cap."""
    ranges: list[tuple[int, int]] = []
    cur = start
    while cur <= end:
        best = cur
        last_cut: int | None = None
        for e in range(cur, min(end, cur + max_lines - 1) + 1):
            if e > cur and estimate_out(lines, cur, e) > target_out:
                break
            best = e
            if lines[e - 1].strip() == "" or NUM_HEAD_RE.match(lines[e - 1]):
                last_cut = e
        if best == cur:
            best = min(cur + max_lines - 1, end)
        elif best < end and last_cut and last_cut - cur + 1 >= max(20, (best - cur + 1) // 2):
            best = last_cut
        ranges.append((cur, best))
        cur = best + 1
    return ranges


def page_map(lines: list[str]) -> dict[int, int]:
    pages: dict[int, int] = {}
    current = 0
    for i, line in enumerate(lines, 1):
        m = re.search(r"<!--\s*page\s+(\d+)", line)
        if m:
            current = int(m.group(1))
        pages[i] = current
    return pages


def section_bounds(lines: list[str], min_lines: int) -> list[tuple[int, int]]:
    total = len(lines)
    starts = [1]
    for i, line in enumerate(lines, 1):
        if re.match(r"^##\s+", line):
            starts.append(i)
    starts = sorted(set(starts))
    bounds = []
    for idx, s in enumerate(starts):
        e = starts[idx + 1] - 1 if idx + 1 < len(starts) else total
        if e >= s:
            bounds.append((s, e))

    merged: list[tuple[int, int]] = []
    for s, e in bounds:
        if merged and (e - s + 1) < min_lines:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    if len(merged) > 1 and merged[0][1] - merged[0][0] + 1 < min_lines:
        merged[0] = (merged[0][0], merged[1][1])
        del merged[1]
    return merged


def merge_small_ranges(ranges: list[tuple[int, int]], min_lines: int) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for a, b in ranges:
        if merged and (b - a + 1) < min_lines:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    if len(merged) > 1 and merged[0][1] - merged[0][0] + 1 < min_lines:
        merged[0] = (merged[0][0], merged[1][1])
        del merged[1]
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineru", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-lines", type=int, default=300)
    ap.add_argument("--target-out", type=int, default=220)
    ap.add_argument("--min-lines", type=int, default=40)
    ap.add_argument("--headings")
    ap.add_argument("--prefix", default="c")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        print(f"ERROR: {out_path} exists; use --force to replan", file=sys.stderr)
        return 1

    lines = Path(args.mineru).read_text(encoding="utf-8").splitlines()
    total = len(lines)
    if total == 0:
        print("ERROR: empty mineru file", file=sys.stderr)
        return 1
    pages = page_map(lines)

    inventory = []
    if args.headings and Path(args.headings).exists():
        inventory = json.loads(Path(args.headings).read_text(encoding="utf-8")).get("headings", [])

    chunks = []
    n = 0
    all_ranges: list[tuple[int, int]] = []
    for s, e in section_bounds(lines, args.min_lines):
        all_ranges.extend(split_section(lines, s, e, args.max_lines, args.target_out))
    for a, b in merge_small_ranges(all_ranges, args.min_lines):
        n += 1
        hid = f"{args.prefix}{n:02d}"
        heads = [h["num"] for h in inventory
                 if h.get("line") and a <= int(h["line"]) <= b]
        eq = 0
        in_display = False
        for i in range(a, b + 1):
            if lines[i - 1].strip() == "$$":
                if not in_display:
                    eq += 1
                in_display = not in_display
            elif ENV_RE.search(lines[i - 1]):
                eq += 1
        page_start, page_end = pages.get(a, 0), pages.get(b, 0)
        page_str = (f"{page_start}-{page_end}"
                    if page_start and page_end and page_start != page_end
                    else str(page_start or ""))
        chunks.append({
            "id": hid,
            "file": f"tmp/chunks/{hid}.md",
            "line_start": a,
            "line_end": b,
            "pages": page_str,
            "page_start": page_start,
            "page_end": page_end,
            "headings": heads,
            "est_out": estimate_out(lines, a, b),
            "density": round(eq * 100 / max(1, b - a + 1), 1),
            "status": "planned",
            "next_line": None,
            "counts": None,
        })

    manifest = {
        "total_lines": total,
        "max_lines": args.max_lines,
        "target_out": args.target_out,
        "chunks": chunks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(f"wrote {out_path}: {len(chunks)} chunks, {total} lines, target_out={args.target_out}")
    for c in chunks:
        print(f"  {c['id']}: {c['line_start']}-{c['line_end']} "
              f"({c['line_end'] - c['line_start'] + 1} lines, est_out={c['est_out']}, "
              f"eq/100={c['density']}) pages={c['pages']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
