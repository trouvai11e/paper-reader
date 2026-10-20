#!/usr/bin/env python3
r"""Source-fidelity report: Original blocks vs the MinerU dump.

The invariant: the `Original` text of every S/E block must equal what the
PDF says. OCR artifacts in the dump (spacing inside math, `<sup>` tags,
`\tag{...}`, redundant braces, `\left`/`\right` noise) are whitelisted —
cleaning them restores the paper, it does not rewrite it. Any divergence
beyond the whitelist means the translator edited the English, which the
verbatim policy forbids.

Report-only by design: exit code is always 0; divergences are printed for
review. Promote to a failing gate later with `--fail` once the whitelist
has been calibrated on a real project.

Usage:
  uv run source_fidelity.py --config reader.config.json --mineru tmp/mineru_full.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from readerlib import load_config, out_dir, parse_blocks, root

PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
TAG_RE = re.compile(r"\\tag\{[^}]*\}")
SUP_RE = re.compile(r"<sup>([^<]*)</sup>")
SUB_RE = re.compile(r"<sub>([^<]*)</sub>")
NOISE_CMD_RE = re.compile(
    r"\\(?:left|right|textstyle|displaystyle|limits|!|,|;|:|\s)")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def normalize_tokens(text: str) -> list[str]:
    """Token stream tolerant to the whitelisted OCR-cleaning rules.

    Whitespace and braces are stripped only inside math segments; prose keeps
    its word boundaries.
    """
    text = PAGE_MARKER_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = SUP_RE.sub(r"\1", text)
    text = SUB_RE.sub(r"\1", text)
    text = NOISE_CMD_RE.sub("", text)
    parts = re.split(r"(\$\$.*?\$\$|\$[^$]*\$)", text, flags=re.DOTALL)
    out: list[str] = []
    for p in parts:
        if p.startswith("$"):
            p = re.sub(r"\s+", "", p).replace("{", "").replace("}", "")
        out.append(p)
    return [t.lower() for t in TOKEN_RE.findall("".join(out))]


def page_tokens(lines: list[str]) -> dict[int, list[str]]:
    """Normalized tokens per source page."""
    pages: dict[int, list[str]] = {}
    current = 0
    for line in lines:
        m = PAGE_MARKER_RE.search(line)
        if m:
            current = int(m.group(1))
        pages.setdefault(current, []).extend(normalize_tokens(line))
    return pages


def _contains(haystack: list[str], needle: list[str]) -> bool:
    if not needle:
        return True
    joined_h = " ".join(haystack)
    return " ".join(needle) in joined_h


def divergent_blocks(blocks: list[dict],
                     pages: dict[int, list[str]]) -> list[tuple[str, int, str]]:
    """(id, page, text-kind) for blocks whose tokens leave the whitelist."""
    bad: list[tuple[str, int, str]] = []
    for b in blocks:
        page = b.get("page") or 0
        hay = pages.get(page, [])
        if not hay:
            continue
        original = " ".join(b.get("original") or [])
        if original and not _contains(hay, normalize_tokens(original)):
            bad.append((b["id"], page, "original"))
        elif b.get("latex") and not _contains(hay, normalize_tokens(b["latex"])):
            bad.append((b["id"], page, "equation"))
    return bad


def report(cfg: dict, mineru_path: str) -> list[tuple[str, int, str]]:
    """Print the report and return the divergent-block list."""
    md_path = out_dir(cfg) / "paper.md"
    if not md_path.exists():
        print(f"ERROR: {md_path} missing; run assemble.py first", file=sys.stderr)
        raise SystemExit(1)
    mineru = Path(mineru_path)
    if not mineru.is_absolute():
        mineru = root(cfg) / mineru
    blocks = parse_blocks(md_path.read_text(encoding="utf-8"))
    pages = page_tokens(mineru.read_text(encoding="utf-8").splitlines())
    bad = divergent_blocks(blocks, pages)
    checked = sum(1 for b in blocks if (b.get("original") or b.get("latex")))
    if bad:
        print(f"source fidelity: {len(bad)}/{checked} blocks diverge beyond "
              "the OCR whitelist")
        for bid, page, kind in bad:
            print(f"  WARN {bid} (p.{page}, {kind}): Original differs from the "
                  "dump; if the dump is an OCR error, fix via ERRATA with a "
                  "reason, otherwise restore the paper's wording")
    else:
        print(f"source fidelity: {checked} blocks match the dump "
              "(modulo OCR whitelist)")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--mineru", required=True)
    ap.add_argument("--fail", action="store_true",
                    help="exit 1 when any block diverges (default: report only)")
    args = ap.parse_args()
    bad = report(load_config(args.config), args.mineru)
    return 1 if (bad and args.fail) else 0


if __name__ == "__main__":
    sys.exit(main())
