#!/usr/bin/env python3
"""Assemble paper.md / source_map.json / translation_notes.md from translated chunks.

Usage: uv run assemble.py --config reader.config.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from readerlib import (
    apply_errata,
    cfg_get,
    clean_text,
    collect_emendations,
    cut_body,
    die,
    effective_status,
    load_chunks,
    load_config,
    load_errata,
    load_inventory,
    load_manifest,
    marker_block_ids,
    normalize_headings,
    out_dir,
    parse_blocks,
    pending_asks,
    promote_headings,
    renumber,
    resolve,
    root,
    strip_front_sections,
    strip_uncertainty_markers,
    uncertainty_ids,
)


def write_paper_md(cfg: dict, body: str, out) -> None:
    title = cfg_get(cfg, "paper.title", "")
    venue_line = cfg_get(cfg, "paper.venue_line", "")
    if not venue_line:
        venue = cfg_get(cfg, "paper.venue", "")
        doi = cfg_get(cfg, "paper.doi", "")
        venue_line = f"{venue}. DOI: {doi}." if doi else venue
    lines = [
        f"# {title}",
        "",
        f"**Authors:** {cfg_get(cfg, 'paper.authors', '')}",
        "",
        f"**Venue:** {venue_line}",
        "",
        f"**中文标题：** {cfg_get(cfg, 'paper.title_zh', '')}",
        "",
        f"**作者（中）：** {cfg_get(cfg, 'paper.authors_zh', '')}",
        "",
        f"**Source file:** `{cfg_get(cfg, 'paper.source_pdf', '')}`",
        "",
        f"**MinerU parse:** doc:{cfg_get(cfg, 'paper.mineru_parse_id', '')}, tier `{cfg_get(cfg, 'paper.mineru_tier', 'standard')}`",
        "",
        f"**License note:** {cfg_get(cfg, 'paper.license_note', '')}",
        "",
        "---",
        "",
        body.strip(),
        "",
    ]
    notes = cfg_get(cfg, "paper.reading_notes", []) or []
    if notes:
        lines += ["---", "", "## 阅读提示（Critical reading notes）", ""]
        for idx, note in enumerate(notes, 1):
            lines.append(f"{idx}. {note}")
        lines.append("")
    (out / "paper.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_source_map(cfg: dict, body: str, out, uncertain: set[str]) -> tuple[int, int, int]:
    blocks = parse_blocks(body)
    seed = resolve(cfg, "pipeline.glossary")
    terms = []
    if seed and seed.exists():
        for line in seed.read_text(encoding="utf-8").splitlines():
            if line.startswith("|") and not line.startswith("|---") and "English" not in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 2:
                    terms.append((cells[0], cells[1], cells[2] if len(cells) > 2 else ""))

    sm_blocks = []
    pages: dict[int, list[str]] = {}
    equations = []
    figures = []
    for idx, b in enumerate(blocks, 1):
        entry = {
            "id": b["id"],
            "page": b["page"] or 1,
            "type": {"equation": "equation", "note": "note"}.get(b["kind"], "paragraph"),
            "order": idx,
            "original_text": clean_text(" ".join(b["original"])),
            "translation": clean_text(" ".join(b["zh"])),
            "confidence": "medium" if b["id"] in uncertain else "high",
        }
        if b["id"] in uncertain:
            entry["uncertain"] = True
        if b["page"]:
            pages.setdefault(b["page"], []).append(b["id"])
        if b["kind"] == "equation":
            num_m = re.search(r"Eq\.\s*\(([^)]+)\)", b["source_tail"])
            entry["equation_number"] = num_m.group(1) if num_m else None
            entry["latex"] = b["latex"]
            entry["image_path"] = None
            equations.append({
                "id": b["id"], "page": b["page"] or 1,
                "equation_number": num_m.group(1) if num_m else None,
                "latex": (b["latex"] or "").replace("\n", " ") or None,
                "confidence": "high", "image_path": None,
            })
        if b["id"].startswith("F") and b["images"]:
            figures.append({
                "id": b["id"], "page": b["page"], "image_path": b["images"][0],
                "images": b["images"], "heading": b.get("heading", ""),
                "placement_hint": "near_first_mention",
            })
        sm_blocks.append(entry)

    source_map = {
        "paper": {
            "title": cfg_get(cfg, "paper.title", ""),
            "venue": f"{cfg_get(cfg, 'paper.venue', '')}, DOI {cfg_get(cfg, 'paper.doi', '')}",
            "source_type": "pdf", "language": "en",
            "source_path": cfg_get(cfg, "paper.source_pdf", ""),
        },
        "blocks": sm_blocks,
        "pages": [{"page": p, "block_ids": ids} for p, ids in sorted(pages.items())],
        "figures": figures,
        "equations": equations,
        "glossary": [{"term": en, "translation": zh, "note": note} for en, zh, note in terms],
    }
    (out / "source_map.json").write_text(
        json.dumps(source_map, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(blocks), len(equations), len(figures)


def write_notes(cfg: dict, tails: dict[str, str], out, body: str) -> None:
    pages = cfg_get(cfg, "paper.pages", "")
    notes = [
        "# Translation Notes", "",
        "## 方法",
        f"- 解析：MinerU，{cfg_get(cfg, 'paper.mineru_tier', 'standard')} 档，"
        f"本地解析（doc:{cfg_get(cfg, 'paper.mineru_parse_id', '')}）"
        + (f"，共 {pages} 页。" if pages else "。"),
        "- 翻译：逐段忠实翻译，术语以术语表为准；公式仅清洗排版噪声，不改写数学内容。",
        ("- 原文政策：Original 以 PDF 页面为准；论文自身的错误原样保留，"
         "中文按正确含义翻译并以「校注」说明；OCR 伪影的清理记入 UNCERTAINTIES。"),
        "- 块编号：S=正文段落，E=展示公式（对应原文 Eq. 编号），C=图/表标题，F=图片卡片，T=表格。",
        f"- 版权：{cfg_get(cfg, 'paper.license_note', '')}",
        "",
    ]
    emendations = collect_emendations(body)
    if emendations:
        notes += ["## 校注汇总", ""] + emendations + [""]
    asks = pending_asks(tails)
    if asks:
        notes += ["## 待确认清单", "",
                  "以下 OCR 存疑项已经过文本层与页面图像两级自验仍无法确认，",
                  ("请对照源 PDF 给出结论；答复写入 ERRATA.json 后，把对应行改写为 "
                   "`- ASK(已解决): ... -> ERRATA <块id>`。"),
                  ""] + [f"- {a}" for a in asks] + [""]
    notes += ["## Chunk 处理报告"]
    for key in sorted(tails):
        notes.append(f"### {key}")
        notes.append("```")
        notes.append(tails[key].strip())
        notes.append("```")
        notes.append("")
    (out / "translation_notes.md").write_text("\n".join(notes) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
    manifest, chunks = load_manifest(cfg)
    for ch in chunks:
        status, next_line, _counts, reason = effective_status(
            root(cfg) / ch["file"], ch.get("allow_empty", False))
        if status != "done":
            extra = f" next_line={next_line}" if next_line is not None else ""
            die(f"chunk {ch['id']} is {status}{extra}; finish it first "
                f"(run chunk_state.py sync). {reason}")
    bodies, tails = load_chunks(cfg, chunks)
    body, mapping = renumber(bodies)
    fixes = load_errata(cfg)
    if fixes:
        body, applied = apply_errata(body, fixes)
        print(f"applied {len(applied)} errata fixes")
    uncertain = uncertainty_ids(tails, mapping) | marker_block_ids(body)
    inline = cfg_get(cfg, "layout.uncertainty_markers", "ledger") == "inline"
    if not inline:
        body, stripped = strip_uncertainty_markers(body)
        if stripped:
            print(f"stripped {stripped} inline uncertainty markers (ledger kept)")
    inventory = load_inventory(cfg)
    body = strip_front_sections(body)
    body = normalize_headings(body, inventory)
    body = promote_headings(body, inventory)
    body = cut_body(body)

    out = out_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    write_paper_md(cfg, body, out)
    n_blocks, n_eq, n_fig = write_source_map(cfg, body, out, uncertain)
    write_notes(cfg, tails, out, body)
    print(f"chunks={len(chunks)} blocks={n_blocks} equations={n_eq} figures={n_fig} "
          f"uncertain={len(uncertain)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
