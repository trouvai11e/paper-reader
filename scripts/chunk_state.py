#!/usr/bin/env python3
"""Chunk state machine: infer status from chunk files, sync the manifest, and
show what to dispatch next.

Usage:
  uv run chunk_state.py --config reader.config.json sync
  uv run chunk_state.py --config reader.config.json status
  uv run chunk_state.py --config reader.config.json next
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from readerlib import (
    cfg_get,
    dispatchable,
    effective_status,
    load_config,
    load_manifest,
    resolve,
    root,
)


def refresh(cfg: dict, write: bool) -> tuple[list[dict], bool]:
    manifest_path = resolve(cfg, "pipeline.manifest")
    manifest, chunks = load_manifest(cfg, strict=False)
    rows = []
    all_done = True
    for ch in chunks:
        fp = root(cfg) / ch["file"]
        status, next_line, counts, reason = effective_status(fp, ch.get("allow_empty", False))
        ch["status"] = status
        ch["next_line"] = next_line
        ch["counts"] = counts
        if status != "done":
            all_done = False
        if write:
            ch["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
        rows.append({"id": ch["id"], "status": status, "next_line": next_line,
                     "counts": counts, "reason": reason, "chunk": ch})
    if write:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")
    return rows, all_done


def print_table(rows: list[dict]) -> None:
    for r in rows:
        c = r["counts"]
        counts = "/".join(str(c.get(k, 0)) for k in ("S", "E", "C", "F", "T"))
        nxt = r["next_line"] if r["next_line"] is not None else "-"
        reason = f"  {r['reason']}" if r["reason"] else ""
        kind = r["chunk"].get("kind", "translate")
        tag = "  [references]" if kind == "references" else ""
        print(f"{r['id']:>4}  {r['status']:<7}  next={nxt!s:<6}  "
              f"counts={counts}{reason}{tag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("command", choices=["sync", "status", "next"])
    args = ap.parse_args()
    cfg = load_config(args.config)
    rows, all_done = refresh(cfg, write=args.command == "sync")
    if args.command in ("sync", "status"):
        print_table(rows)
        if args.command == "sync":
            print(f"PASS sync: {len(rows)} chunks, all_done={all_done}")
            return 0
        return 0 if all_done else 1
    # next: dispatch only within the earliest unfinished section, so sections
    # are translated in order (terminology seeds grow monotonically) while
    # chunks inside one section may still go to parallel subagents.
    failed = [r for r in rows if r["status"] == "failed"]
    if failed:
        for r in failed:
            print(f"repair: {r['id']} ({r['reason']})")
        return 1
    max_agents = int(cfg_get(cfg, "pipeline.max_agents", 4) or 4)
    ready = dispatchable(rows, max_agents)
    if not ready:
        leftovers = [r for r in rows if r["status"] != "done"]
        if leftovers and all(r["chunk"].get("kind") == "references" for r in leftovers):
            print("only references chunks pending; run gen_references.py")
        else:
            print("all chunks done; nothing to dispatch")
        return 1
    for r in ready:
        ch = r["chunk"]
        start = r["next_line"] or ch["line_start"]
        sec = ch.get("section_title") or ch.get("section") or "?"
        print(f"next: {ch['id']} lines {start}-{ch['line_end']} "
              f"(est_out={ch.get('est_out', '?')}, section={sec}) -> {ch['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
