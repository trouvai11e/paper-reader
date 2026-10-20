#!/usr/bin/env python3
"""Quality gates for a paper-reader project.

Usage:
  uv run check_reader.py --config reader.config.json --stage chunks
  uv run check_reader.py --config reader.config.json --stage assemble
  uv run check_reader.py --config reader.config.json --stage build
  uv run check_reader.py --config reader.config.json --stage all
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys

from readerlib import (
    ANCHOR_RE,
    cfg_get,
    effective_status,
    fidelity_missing,
    load_asset_inventory,
    load_config,
    load_errata,
    load_inventory,
    load_manifest,
    out_dir,
    root,
)


class Checker:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def check(self, ok: bool, msg: str) -> None:
        if not ok:
            self.errors.append(msg)

    def report(self, stage: str) -> int:
        if self.errors:
            print(f"FAIL {stage}:")
            for e in self.errors:
                print(f"  - {e}")
            return 1
        print(f"PASS {stage}")
        return 0


def check_chunks(cfg: dict, c: Checker) -> None:
    try:
        manifest, chunks = load_manifest(cfg, strict=False)
    except SystemExit:
        c.check(False, "manifest coverage / chunk files (see error above)")
        return
    ids: set[str] = set()
    n_refs = 0
    for ch in chunks:
        fp = root(cfg) / ch["file"]
        status, next_line, counts, reason = effective_status(
            fp, ch.get("allow_empty", False))
        extra = f" next_line={next_line}" if next_line is not None else ""
        c.check(status == "done", f"{ch['id']}: {status}{extra} {reason}".strip())
        if not fp.exists():
            continue
        text = fp.read_text(encoding="utf-8")
        anchors = ANCHOR_RE.findall(text)
        c.check(len(anchors) == len(set(anchors)), f"{ch['id']}: duplicate local anchors")
        for a in anchors:
            if a in ids:
                c.check(False, f"{ch['id']}: local id {a} reused across chunks")
            ids.add(a)
        if ch.get("kind") == "references":
            rm = re.search(r"refs=(\d+)", text)
            reported = int(rm.group(1)) if rm else -1
            body = text.split("\nUNCERTAINTIES:", 1)[0]
            listed = len(re.findall(r"^\d+\.\s", body, re.MULTILINE))
            c.check(reported == listed,
                    f"{ch['id']}: REPORT refs={reported} but {listed} listed entries")
            n_refs += 1
    print(f"chunks={len(chunks)} manifest=ok references_chunks={n_refs}")


def check_status(cfg: dict, c: Checker) -> None:
    try:
        _manifest, chunks = load_manifest(cfg, strict=False)
    except SystemExit:
        c.check(False, "manifest coverage / chunk files (see error above)")
        return
    for ch in chunks:
        status, next_line, counts, reason = effective_status(
            root(cfg) / ch["file"], ch.get("allow_empty", False))
        nxt = next_line if next_line is not None else "-"
        cnt = "/".join(str(counts.get(k, 0)) for k in ("S", "E", "C", "F", "T"))
        kind = " [references]" if ch.get("kind") == "references" else ""
        print(f"{ch['id']:>4}  {status:<7}  next={str(nxt):<6}  counts={cnt}  "
              f"lines={ch['line_start']}-{ch['line_end']}  est_out={ch.get('est_out', '?')}{kind}")
        c.check(status == "done", f"{ch['id']}: {status} {reason}".strip())


def check_assemble(cfg: dict, c: Checker) -> None:
    out = out_dir(cfg)
    paper = out / "paper.md"
    c.check(paper.exists(), "paper.md missing")
    if not paper.exists():
        return
    md = paper.read_text(encoding="utf-8")
    anchors = ANCHOR_RE.findall(md)
    c.check(len(anchors) == len(set(anchors)), "duplicate global anchors")
    c.check("p.?" not in md, "paper.md still contains 'p.?' placeholders")
    for bad in ("## 目录（Contents）", "## 术语表（Terminology）", "## 公式索引"):
        c.check(bad not in md, f"paper.md still contains forbidden section: {bad}")
    c.check("〔?〕" not in md, "paper.md still contains inline 〔?〕 markers")
    if "（OCR" in md or "原文为" in md:
        print("WARN: body still has OCR commentary; move it to translation_notes.md")
    cjk_math = [m.group(0) for m in re.finditer(r"\$([^$\n]+)\$", md)
                if re.search(r"[\u4e00-\u9fff]", m.group(0))]
    c.check(not cjk_math, f"CJK inside inline math (will not render): {cjk_math[:3]}")

    parts = re.split(r'(?=<a id="[SETF]\d+"></a>)', md)
    by_id = {}
    for part in parts:
        m = re.match(r'\s*<a id="([SETF]\d+)"></a>', part)
        if m:
            by_id[m.group(1)] = part
    for fix in load_errata(cfg):
        block = by_id.get(fix["block"], "")
        c.check(bool(block), f"errata block {fix['block']} missing")
        if block:
            c.check(fix["new"] in block, f"errata new text missing in {fix['block']}")
            c.check(fix["old"] not in block, f"errata old text still in {fix['block']}")

    sm_path = out / "source_map.json"
    c.check(sm_path.exists(), "source_map.json missing")
    sm = {}
    if sm_path.exists():
        sm = json.loads(sm_path.read_text(encoding="utf-8"))
        c.check(len(sm.get("blocks", [])) == len(anchors),
                f"source_map blocks={len(sm.get('blocks', []))} != anchors={len(anchors)}")
        counts = {"high": 0, "medium": 0}
        for b in sm.get("blocks", []):
            counts[b.get("confidence", "high")] = counts.get(b.get("confidence", "high"), 0) + 1
        print(f"confidence: high={counts.get('high', 0)} medium={counts.get('medium', 0)}")

    tex = out / "reader.tex"
    targets: list[tuple[str, str]] = [("paper.md", md)]
    if tex.exists():
        targets.append(("reader.tex", tex.read_text(encoding="utf-8")))
    else:
        c.check(False, "reader.tex missing; run md2tex.py")
    if sm.get("blocks"):
        for name, text in targets:
            missing = fidelity_missing(sm["blocks"], text)
            c.check(not missing, f"{name} missing text for blocks: {missing[:8]}"
                    + (" ..." if len(missing) > 8 else ""))

    for img in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md):
        if img.startswith(("http://", "https://")):
            continue
        c.check((out / img).exists(), f"missing image: {img}")

    inv = load_inventory(cfg)
    for h in inv.get("headings", []):
        num = h["num"]
        pat = rf"^(#+)\s+{re.escape(num)}\.?\s"
        found = [len(m.group(1)) for m in re.finditer(pat, md, re.M)]
        c.check(bool(found), f"heading {num} missing from paper.md")
        if found and h.get("level"):
            c.check(found[0] == int(h["level"]),
                    f"heading {num} level={found[0]}, expected {h['level']}")

    assets = load_asset_inventory(cfg)
    for item in assets:
        label = r"Table" if item["kind"] == "table" else r"(?:Fig\.|Figure)"
        pat = rf"^#+\s*{label}\s*{re.escape(item['num'])}[.:]?\s"
        c.check(bool(re.search(pat, md, re.M)),
                f"{item['kind']} {item['num']} (line {item.get('line')}) missing from paper.md")
    print(f"anchors={len(anchors)} headings={len(inv.get('headings', []))} "
          f"tables+figures={len(assets)}")


def check_build(cfg: dict, c: Checker) -> None:
    out = out_dir(cfg)
    pdf = out / "reader.pdf"
    log = out / "reader.log"
    c.check(pdf.exists(), "reader.pdf missing")
    c.check(log.exists(), "reader.log missing")
    if pdf.exists():
        for newer in ("reader.tex", "paper.md"):
            p = out / newer
            if p.exists() and pdf.stat().st_mtime < p.stat().st_mtime:
                c.check(False, f"reader.pdf older than {newer}; rebuild before checking")
    if log.exists() and (out / "reader.tex").exists():
        if log.stat().st_mtime < (out / "reader.tex").stat().st_mtime:
            c.check(False, "reader.log older than reader.tex; rebuild before checking")
    if log.exists():
        errors = [ln for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
                  if ln.startswith("!")]
        c.check(not errors, f"LaTeX errors: {errors[:3]}")
        m = re.search(r"Output written on .*?\((\d+) pages?\)",
                      log.read_text(encoding="utf-8", errors="replace"))
        if m:
            print(f"pages={m.group(1)}")

    font = cfg_get(cfg, "layout.chinesefont", "founder")
    if font == "founder":
        pdffonts = shutil.which("pdffonts")
        if pdffonts and pdf.exists():
            fonts = subprocess.run([pdffonts, str(pdf)], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace").stdout
            c.check("FZ" in fonts, "chinesefont=founder requested but no FZ font in PDF")
        elif not pdffonts:
            print("WARN: pdffonts not found; skipped font gate")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--stage",
                    choices=["status", "chunks", "assemble", "build", "all"],
                    default="all")
    args = ap.parse_args()
    cfg = load_config(args.config)
    c = Checker()
    if args.stage == "status":
        check_status(cfg, c)
        return c.report("status")
    stages = ["chunks", "assemble", "build"] if args.stage == "all" else [args.stage]
    failed = False
    for stage in stages:
        if stage == "chunks":
            check_chunks(cfg, c)
        elif stage == "assemble":
            check_assemble(cfg, c)
        elif stage == "build":
            check_build(cfg, c)
        failed = bool(c.report(stage)) or failed
        c.errors.clear()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
