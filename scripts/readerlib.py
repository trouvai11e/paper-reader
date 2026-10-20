"""Shared utilities for the paper-reader pipeline.

Stdlib only. Imported by assemble.py / md2tex.py / check_reader.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ANCHOR_RE = re.compile(r'<a id="([SECTF]\d+(?:-\d+)?)"></a>')
ID_TOKEN_RE = re.compile(r"\b([SECTF])(\d+)-(\d+)\b")
SOURCE_LINE_RE = re.compile(r"\*\*Source:\*\*\s*p\.(\d+)\s+([SECTF]\d+-\d+)([^*\n]*)")
HEAD_RE = re.compile(r"^(#{2,4})\s+(\d+(?:\.\d+)*)\.?\s+(.*)$")
NUM_HEAD_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+")
ENV_BEGIN_RE = re.compile(
    r"\\begin\{(equation|align|aligned|gather|multline|cases|array|pmatrix|bmatrix)\}")
ENV_END_RE = re.compile(
    r"\\end\{(equation|align|aligned|gather|multline|cases|array|pmatrix|bmatrix)\}")
REF_TITLE_RE = re.compile(r"参考文献|references?", re.IGNORECASE)


# ---------------------------------------------------------------- config

def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_config(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        die(f"config not found: {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg["_root"] = str(p.resolve().parent)
    return cfg


def cfg_get(cfg: dict, dotted: str, default=None):
    cur = cfg
    for key in dotted.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def root(cfg: dict) -> Path:
    return Path(cfg["_root"])


def resolve(cfg: dict, dotted: str, default=None) -> Path | None:
    val = cfg_get(cfg, dotted, default)
    if val is None:
        return None
    p = Path(str(val))
    return p if p.is_absolute() else root(cfg) / p


def out_dir(cfg: dict) -> Path:
    return resolve(cfg, "pipeline.output_dir", "reader")


# ---------------------------------------------------------------- manifest

def load_manifest(cfg: dict, strict: bool = True) -> tuple[dict, list[dict]]:
    mp = resolve(cfg, "pipeline.manifest")
    if mp is None or not mp.exists():
        die(f"manifest not found: {mp}")
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    chunks = sorted(manifest.get("chunks", []), key=lambda c: c["line_start"])
    if not chunks:
        die("manifest has no chunks")
    expected = 1
    for c in chunks:
        if c["line_start"] != expected:
            die(
                f"manifest gap/overlap at {c['id']}: starts {c['line_start']}, "
                f"expected {expected}"
            )
        expected = c["line_end"] + 1
    total = manifest.get("total_lines")
    if total and expected <= total:
        die(f"manifest ends at line {expected - 1}, total_lines={total}")
    if strict:
        for c in chunks:
            fp = root(cfg) / c["file"]
            if not fp.exists():
                die(f"missing chunk file for {c['id']}: {fp}")
    return manifest, chunks


def load_chunks(cfg: dict, chunks: list[dict]) -> tuple[list[str], dict[str, str]]:
    tails: dict[str, str] = {}
    bodies: list[str] = []
    for c in chunks:
        fp = root(cfg) / c["file"]
        text = fp.read_text(encoding="utf-8")
        m = re.search(r"\nUNCERTAINTIES:", text)
        if m:
            tails[f"{c['id']}:uncertainties"] = text[m.start():]
            text = text[: m.start()]
        m = re.search(r"\nREPORT:", text)
        if m:
            tails[f"{c['id']}:report"] = text[m.start():]
            text = text[: m.start()]
        bodies.append(text.rstrip() + "\n")
    return bodies, tails


def load_inventory(cfg: dict) -> dict:
    ip = resolve(cfg, "pipeline.headings")
    if ip and ip.exists():
        return json.loads(ip.read_text(encoding="utf-8"))
    return {"headings": []}


def load_asset_inventory(cfg: dict) -> list[dict]:
    ip = resolve(cfg, "pipeline.inventory")
    if ip and ip.exists():
        data = json.loads(ip.read_text(encoding="utf-8"))
        return data.get("items", data.get("inventory", []))
    return []


# ---------------------------------------------------------------- ids

def renumber(texts: list[str]) -> tuple[str, dict[str, str]]:
    """Assign global sequential ids per prefix and update all references.

    Returns (body, mapping) where mapping maps local ids (S1-001) to global (S001).
    """
    mapping: dict[str, str] = {}
    counters = {"S": 0, "E": 0, "C": 0, "F": 0, "T": 0}

    def repl(m: re.Match) -> str:
        old = m.group(1)
        prefix = old[0]
        if old not in mapping:
            counters[prefix] += 1
            mapping[old] = f"{prefix}{counters[prefix]:03d}"
        return f'<a id="{mapping[old]}"></a>'

    joined = "\n".join(texts)
    joined = ANCHOR_RE.sub(repl, joined)

    def tok_repl(m: re.Match) -> str:
        old = m.group(0)
        return mapping.get(old, old)

    joined = ID_TOKEN_RE.sub(tok_repl, joined)
    joined = joined.replace(r"\llbracket", r"[\![").replace(r"\rrbracket", r"]\!]")
    out_lines: list[str] = []
    last_anchor = "S001"
    for line in joined.splitlines():
        if "TBD-ANCHOR" in line:
            line = line.replace("TBD-ANCHOR", last_anchor)
        m = ANCHOR_RE.search(line)
        if m and m.group(1)[0] in "SE":
            last_anchor = m.group(1)
        out_lines.append(line)
    return "\n".join(out_lines), mapping


# ---------------------------------------------------------------- uncertainty

MARKER = "〔?〕"


def strip_uncertainty_markers(text: str) -> tuple[str, int]:
    """Remove inline `〔?〕` markers and tidy the seam they leave."""
    count = text.count(MARKER)
    if not count:
        return text, 0
    # Keep a space when a math segment meets CJK; otherwise remove the seam.
    text = re.sub(r"(\$[^$]*\$|[}$])\s*" + re.escape(MARKER) + r"\s*(?=[\u4e00-\u9fff])",
                  r"\1 ", text)
    text = text.replace(MARKER, "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([，。；：、）)])", r"\1", text)
    text = re.sub(r"([（(]) +", r"\1", text)
    return text, count


def uncertainty_ids(tails: dict[str, str], mapping: dict[str, str]) -> set[str]:
    """Global block ids mentioned in UNCERTAINTIES ledgers."""
    out: set[str] = set()
    for key, text in tails.items():
        if not key.endswith(":uncertainties"):
            continue
        for local in re.findall(r"\b([SETF]\d+-\d+)\b", text):
            if local in mapping:
                out.add(mapping[local])
    return out


def marker_block_ids(body: str) -> set[str]:
    """Global block ids that still carry an inline marker."""
    out: set[str] = set()
    current = ""
    for line in body.splitlines():
        m = ANCHOR_RE.search(line)
        if m:
            current = m.group(1)
        if MARKER in line and current:
            out.add(current)
    return out


# ---------------------------------------------------------------- chunk state

def line_costs(lines: list[str]) -> list[float]:
    """Per-line estimated output cost; display-math opening lines cost extra.

    Mirrors the `1.1 * text + 3.5 * display` estimate, exposed per line so the
    planner can use prefix sums instead of re-scanning ranges.
    """
    costs: list[float] = []
    in_display = False
    for line in lines:
        cost = 1.1
        stripped = line.strip()
        if stripped == "$$":
            if not in_display:
                cost += 3.5
            in_display = not in_display
        elif ENV_BEGIN_RE.search(line):
            cost += 3.5
        costs.append(cost)
    return costs


def math_mask(lines: list[str]) -> list[bool]:
    """True for lines inside a `$$...$$` block or a math environment."""
    mask: list[bool] = []
    in_display = False
    env_depth = 0
    for line in lines:
        stripped = line.strip()
        mask.append(in_display or env_depth > 0 or stripped == "$$")
        if stripped == "$$":
            in_display = not in_display
        env_depth += len(ENV_BEGIN_RE.findall(line))
        env_depth = max(0, env_depth - len(ENV_END_RE.findall(line)))
    return mask


def is_references_heading(text: str) -> bool:
    """True when a heading title denotes the bibliography section."""
    return bool(REF_TITLE_RE.search(text or ""))


def chunk_key(ch: dict) -> tuple[int, int]:
    """Ordering key for manifest chunks (stable even without section fields)."""
    return (ch.get("line_start", 0), ch.get("line_end", 0))


def dispatchable(rows: list[dict], max_agents: int) -> list[dict]:
    """Chunks ready to dispatch, restricted to the earliest unfinished section.

    `rows` are dicts with at least `status` and `chunk`. Chunks whose
    `kind` is not `"translate"` (e.g. `"references"`) are generated by scripts
    and are never dispatched to subagents. Within the earliest section that
    still has pending chunks, partials come first, then planned chunks, capped
    at `max_agents`.
    """
    pending = [r for r in rows
               if r["status"] in ("partial", "planned")
               and r["chunk"].get("kind", "translate") == "translate"]
    if not pending:
        return []
    first = min(pending, key=lambda r: chunk_key(r["chunk"]))["chunk"]
    section = first.get("section")
    if section is None:  # legacy manifest without section fields
        same_section = pending
    else:
        same_section = [r for r in pending if r["chunk"].get("section") == section]
    same_section.sort(key=lambda r: (0 if r["status"] == "partial" else 1,
                                     chunk_key(r["chunk"])))
    return same_section[:max(1, max_agents)]


def block_counts(text: str) -> dict[str, int]:
    counts = {"S": 0, "E": 0, "C": 0, "F": 0, "T": 0}
    for anchor in ANCHOR_RE.findall(text):
        if anchor[0] in counts:
            counts[anchor[0]] += 1
    return counts


def effective_status(path: Path, allow_empty: bool = False) -> tuple[str, int | None, dict[str, int], str]:
    """Infer (status, next_line, counts, reason) from a chunk file."""
    empty = {"S": 0, "E": 0, "C": 0, "F": 0, "T": 0}
    if not path.exists():
        return "planned", None, empty, "file missing"
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return "failed", None, empty, "empty file"
    counts = block_counts(text)
    m = re.search(r"next_line=(\d+)", text)
    next_line = int(m.group(1)) if m else None
    rm = re.search(r"REPORT:\s*S=(\d+)\s+E=(\d+)", text)
    if not rm:
        if allow_empty and "REPORT:" in text:
            return "done", None, counts, ""
        return "failed", next_line, counts, "missing REPORT S=/E= counts"
    if counts["S"] != int(rm.group(1)) or counts["E"] != int(rm.group(2)):
        return ("failed", next_line, counts,
                f"REPORT S={rm.group(1)} E={rm.group(2)} but anchors "
                f"S={counts['S']} E={counts['E']}")
    if next_line is not None:
        return "partial", next_line, counts, ""
    return "done", None, counts, ""


# ---------------------------------------------------------------- fidelity

def _plain_text(text: str) -> str:
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    return text


def normalize_for_fidelity(text: str) -> str:
    text = _plain_text(text)
    return re.sub(r"[^A-Za-z\u4e00-\u9fff]+", "", text).lower()


def _cjk_runs(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]{8,}", _plain_text(text))


def _word_shingles(text: str, n: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-z]+", _plain_text(text))
    if len(words) < n + 2:
        return []
    return ["".join(words[i:i + n]).lower() for i in range(len(words) - n + 1)]


def fidelity_missing(blocks: list[dict], tex: str) -> list[str]:
    """Block ids whose original or translated text is absent from reader.tex."""
    tex_norm = normalize_for_fidelity(tex)
    missing: list[str] = []
    for b in blocks:
        if b.get("type") == "equation":
            continue
        text = b.get("original_text") or ""
        zh = b.get("translation") or ""
        if len(text) >= 40:
            shingles = _word_shingles(text)
            if shingles:
                hit = sum(1 for s in shingles if s in tex_norm) / len(shingles)
                if hit < 0.8:
                    missing.append(b["id"])
                    continue
        runs = _cjk_runs(zh)
        if runs:
            probes = {runs[0], runs[len(runs) // 2], runs[-1]}
            if any(p not in tex_norm for p in probes):
                missing.append(b["id"])
    return missing


# ---------------------------------------------------------------- inventory

CAPTION_RE = re.compile(
    r"^(?:#{1,4}\s*)?(?:\*\*)?(Table|Figure|Fig\.)\s*([0-9]+(?:[.\-][0-9]+)*)[.:]?\s+(.+)$",
    re.M,
)


def caption_inventory(text: str) -> list[dict]:
    """Table/figure captions with line numbers, for completeness checks."""
    items: list[dict] = []
    for m in CAPTION_RE.finditer(text):
        kind = "table" if m.group(1).lower().startswith("table") else "figure"
        line = text[:m.start()].count("\n") + 1
        caption = m.group(3).strip()
        if len(caption) < 6:
            continue
        items.append({"kind": kind, "num": m.group(2), "line": line, "caption": caption[:160]})
    return items


# ---------------------------------------------------------------- errata

def load_errata(cfg: dict) -> list[dict]:
    ep = resolve(cfg, "pipeline.errata", "reader/ERRATA.json")
    if ep and ep.exists():
        data = json.loads(ep.read_text(encoding="utf-8"))
        return data.get("fixes", [])
    return []


def apply_errata(body: str, fixes: list[dict]) -> tuple[str, list[str]]:
    """Apply per-block old->new fixes. Returns (body, applied block ids)."""
    if not fixes:
        return body, []
    parts = re.split(r'(?=<a id="[SETF]\d+"></a>)', body)
    applied: list[str] = []
    for fix in fixes:
        bid = fix["block"]
        hit = False
        for idx, part in enumerate(parts):
            m = re.match(r'\s*<a id="([SETF]\d+)"></a>', part)
            if not m or m.group(1) != bid:
                continue
            if fix["old"] not in part:
                continue
            parts[idx] = part.replace(fix["old"], fix["new"])
            applied.append(bid)
            hit = True
            break
        if not hit:
            die(f"errata not applicable: block {bid} does not contain {fix['old']!r}")
    return "".join(parts), applied




# ---------------------------------------------------------------- headings

def heading_line(num: str, inv: dict | None, en_fb: str, zh_fb: str) -> tuple[str, str]:
    inv = inv or {}
    en = inv.get("en") or en_fb
    zh = inv.get("zh") or zh_fb
    level = int(inv.get("level") or (num.count(".") + 2))
    sep = ". " if "." not in num else " "
    return "#" * level, f"{num}{sep}{zh}（{en}）"


def split_heading_sentence(text: str):
    """Split `3.3.1. Heading. body...` into (num, heading, body)."""
    m = NUM_HEAD_RE.match(text)
    if not m:
        return None
    rest = text[m.end():].strip()
    if rest.startswith("**"):
        end = rest.find("**", 2)
        if end == -1:
            return None
        heading = rest[2:end].strip()
        after = rest[end + 2:].strip()
        return m.group(1), heading.rstrip(".。 "), after
    mm = re.search(r"[.。]", rest)
    if not mm:
        return None
    heading = rest[: mm.start()].strip()
    after = rest[mm.end():].strip()
    return m.group(1), heading, after


def normalize_headings(body: str, inventory: dict) -> str:
    by_num = {h["num"]: h for h in inventory.get("headings", [])}
    out = []
    for line in body.splitlines():
        m = HEAD_RE.match(line)
        if m and m.group(2) in by_num:
            hashes, title = heading_line(m.group(2), by_num[m.group(2)], m.group(3), m.group(3))
            out.append(f"{hashes} {title}")
        else:
            out.append(line)
    return "\n".join(out)


def promote_headings(body: str, inventory: dict) -> str:
    """Turn paragraphs that start with `3.1. ...` into real headings."""
    by_num = {h["num"]: h for h in inventory.get("headings", [])}
    parts = re.split(r'(?=<a id="[SECTF]\d+(?:-\d+)?"></a>)', body)
    out: list[str] = []
    for part in parts:
        lines = part.splitlines()
        oi = next((i for i, l in enumerate(lines) if l.startswith("**Original:**")), None)
        zi = next((i for i, l in enumerate(lines) if re.match(r"\*\*中文[：:]", l)), None)
        if oi is None or zi is None:
            out.append(part)
            continue
        o_val = lines[oi][len("**Original:**"):].strip()
        z_val = re.sub(r"^\*\*中文[：:]\*\*\s*", "", lines[zi]).strip()
        ho = split_heading_sentence(o_val)
        hz = split_heading_sentence(z_val)
        if not (ho and hz and ho[0] == hz[0]):
            out.append(part)
            continue
        num = ho[0]
        hashes, title = heading_line(num, by_num.get(num), ho[1], hz[1])
        lines[oi] = "**Original:** " + ho[2]
        lines[zi] = "**中文：** " + hz[2]
        lines.insert(oi, f"{hashes} {title}")
        lines.insert(oi + 1, "")
        trail = len(part) - len(part.rstrip("\n"))
        out.append("\n".join(lines) + "\n" * trail)
    return "".join(out)


def strip_front_sections(body: str) -> str:
    for title in ("目录（Contents）", "术语表（Terminology）", "公式索引"):
        body = re.sub(rf"^## {re.escape(title)}\n.*?(?=^## |\Z)", "", body, flags=re.S | re.M)
    return body.lstrip("\n")


def cut_body(md: str) -> str:
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('<a id="') or line.startswith("## "):
            return "\n".join(lines[i:])
    return md


# ---------------------------------------------------------------- markdown

def esc_outside_math(s: str) -> str:
    out = []
    parts = re.split(r"(\$[^$]*\$)", s)
    for p in parts:
        if p.startswith("$") and p.endswith("$") and len(p) > 1:
            out.append(p)
        else:
            out.append(p.replace("%", r"\%").replace("&", r"\&").replace("_", r"\_"))
    return "".join(out)


def inline_md(s: str) -> str:
    s = esc_outside_math(s)
    s = re.sub(r"\[([^\]]+)\]\(#([A-Za-z0-9_-]+)\)", r"\\hyperref[\2]{\1}", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"<sup>([^<]+)</sup>", r"$^{\1}$", s)
    s = re.sub(r"<sub>([^<]+)</sub>", r"$_{\1}$", s)
    # Strip only known HTML tags. A generic `<[^>]+>` also eats math comparisons
    # such as `$a<b$ ... $c>d$`.
    s = re.sub(r"</?(?:a|sup|sub|br|span|p|div|em|strong|code|i|b)(?:\s[^>]*)?/?>",
               "", s, flags=re.I)
    s = s.replace("~", r"\textasciitilde{}")
    return s


def strip_heading_num(title: str) -> str:
    t = re.sub(r"^附录\s+[A-Z]\.\s*", "", title)
    t = re.sub(r"^\d+(\.\d+)*\.*\s*", "", t)
    return t


def tex_escape_plain(s: str) -> str:
    return s.replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")


# ---------------------------------------------------------------- preamble

def class_options(cfg: dict) -> list[str]:
    opts = list(cfg_get(cfg, "layout.class_options", ["cn", "normal", "blue", "12pt"]))
    font = cfg_get(cfg, "layout.chinesefont", "founder")
    if font and font != "ctexfont" and not any(o.startswith("chinesefont=") for o in opts):
        opts.append(f"chinesefont={font}")
    return opts


def preamble(cfg: dict) -> str:
    opts = ",".join(class_options(cfg))
    title = cfg_get(cfg, "paper.title_tex") or cfg_get(cfg, "paper.title", "")
    title_zh = cfg_get(cfg, "paper.title_zh", "")
    title_tex = f"{title}（{title_zh}）" if title_zh else title
    authors = cfg_get(cfg, "paper.authors", "")
    venue = tex_escape_plain(cfg_get(cfg, "paper.venue", ""))
    doi = cfg_get(cfg, "paper.doi", "")

    header: list[str] = []
    if doi:
        header.append(f"{venue}, DOI: \\href{{https://doi.org/{doi}}}{{{doi}}}")
    elif venue:
        header.append(venue)
    msc = cfg_get(cfg, "paper.msc", "")
    if msc:
        header.append("2020 Mathematics Subject Classification: " + msc)
    keywords = tex_escape_plain(cfg_get(cfg, "paper.keywords", ""))
    if keywords:
        header.append("Keywords: " + keywords)
    note = cfg_get(cfg, "paper.copyright_note", "")
    if note:
        header.append(note)
    header_tex = "\n".join(h + r"\\" for h in header)

    return (
        "% !TEX program = xelatex\n"
        f"\\documentclass[{opts}]{{elegantnote}}\n"
        "\\usepackage{amsmath}\n"
        "\\usepackage{amssymb}\n"
        "\\usepackage{longtable,booktabs,array}\n"
        "\\renewcommand{\\arraystretch}{1.25}\n"
        "% ---- bilingual reader macros ----\n"
        "\\newenvironment{origpar}{\\par\\begingroup\\small\\color{black!65}\\ignorespaces}"
        "{\\par\\endgroup\\par\\medskip}\n"
        "\\newcommand{\\srctag}[1]{{\\footnotesize\\color{gray}\\hfill [#1]\\par}\\nopagebreak}\n"
        "\\newcommand{\\notepar}[1]{\\par\\begingroup\\small\\itshape\\color{black!55}#1"
        "\\par\\endgroup\\smallskip}\n"
        f"\\title{{{title_tex}}}\n"
        f"\\author{{{authors}}}\n"
        f"\\institute{{{venue}}}\n"
        "\\date{\\today}\n"
        "\\setcounter{secnumdepth}{3}\n"
        "\\begin{document}\n"
        "\\maketitle\n"
        "\\noindent\\small\\color{black!70}"
        + header_tex
        + "\n\\normalsize\\color{black}\\par\\medskip\\hrule\\medskip\n"
    )


# ---------------------------------------------------------------- md -> tex

def merge_captions(md: str) -> str:
    """Merge figure/table captions into the heading: `Fig. 1.1. EN（中文）`."""
    parts = re.split(r'(?=<a id="[FT]\d+"></a>)', md)
    out: list[str] = []
    for part in parts:
        m = re.match(r'\s*<a id="([FT]\d+)"></a>', part)
        if not m:
            out.append(part)
            continue
        hl = re.search(r"^### (.+)$", part, re.M)
        en = re.search(r"^\*\*Original caption:\*\*\s*(.+)$", part, re.M)
        zh = re.search(r"^\*\*中文[图表]注：\*\*\s*(.+)$", part, re.M)
        if not (hl and en and zh):
            print(f"WARN: caption incomplete in {m.group(1)}", file=sys.stderr)
            out.append(part)
            continue
        head = hl.group(1).strip()
        lm = re.match(r"^(Fig\.|Table)\s*([0-9A-Za-z.]+)", head)
        prefix = f"{lm.group(1)} {lm.group(2)}" if lm else head.split()[0]
        num = re.escape(lm.group(2)) if lm else r"[\d.]+"
        en_body = re.sub(r"^(?:Figure|Fig\.|Table)\s*" + num + r"\.?\s*", "", en.group(1).strip())
        zh_body = re.sub(r"^(?:图|表)\s*" + num + r"\.?\s*", "", zh.group(1).strip())
        zh_body = zh_body.rstrip("。")
        new_head = f"### {prefix} {en_body}（{zh_body}）"
        part = part.replace(hl.group(0), new_head, 1)
        part = part.replace(en.group(0), "", 1)
        part = part.replace(zh.group(0), "", 1)
        out.append(part)
    return "".join(out)


def tex_table(tbl_lines: list[str]) -> str:
    rows = []
    for ln in tbl_lines:
        if re.match(r"^\|(\s*:?-+:?\s*\|)+$", ln):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    cols = "".join(["p{0.115\\textwidth}" if i == 0 else "c" for i in range(ncol)])
    out = ["\\nopagebreak[4]", "\\begin{center}\\small", f"\\begin{{longtable}}{{{cols}}}", "\\toprule"]
    header = rows[0] + [""] * (ncol - len(rows[0]))
    out.append(" & ".join(inline_md(c) for c in header) + r" \\")
    out.append("\\midrule")
    out.append(r"\endfirsthead")
    out.append("\\toprule")
    out.append(" & ".join(inline_md(c) for c in header) + r" \\")
    out.append("\\midrule")
    out.append(r"\endhead")
    for r in rows[1:]:
        r = r + [""] * (ncol - len(r))
        out.append(" & ".join(inline_md(c) for c in r) + r" \\")
    out.append("\\bottomrule")
    out.append("\\end{longtable}")
    out.append("\\end{center}")
    return "\n".join(out)


def md_to_tex(md: str, cfg: dict) -> str:
    md = merge_captions(md)
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    appendix_started = False
    in_eq = False
    eq_buf: list[str] = []
    para_buf: list[str] = []
    pending_eq: str | None = None
    fig_open = False
    starred = tuple(cfg_get(cfg, "layout.starred_sections", ["Abstract", "阅读提示"]))

    def flush_para() -> None:
        if para_buf:
            out.append("\n" + inline_md(" ".join(para_buf)) + "\n")
            para_buf.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if in_eq:
            if stripped == "$$":
                if pending_eq is not None:
                    out.append("\\begin{equation}")
                    out.extend(eq_buf)
                    out.append("\\tag{%s}" % pending_eq)
                    out.append("\\end{equation}\n")
                else:
                    out.append("\\[")
                    out.extend(eq_buf)
                    out.append("\\]\n")
                eq_buf.clear()
                in_eq = False
                pending_eq = None
            else:
                eq_buf.append(line)
            i += 1
            continue
        if stripped == "$$":
            flush_para()
            in_eq = True
            i += 1
            continue
        m = ANCHOR_RE.search(line)
        if m:
            flush_para()
            out.append(f"\\hypertarget{{{m.group(1)}}}{{}}%")
            i += 1
            continue
        hm = re.match(r"^(#{1,4})\s+(.*)$", line)
        if hm:
            flush_para()
            level = len(hm.group(1))
            title = hm.group(2).strip()
            plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title)
            core = strip_heading_num(plain)
            if re.match(r"^参考文献", plain):
                out.append("\\section*{参考文献（References）}")
            elif re.match(r"^(Fig\.|Table\s)", plain):
                if plain.startswith("Fig."):
                    out.append("\\noindent\\begin{minipage}{\\linewidth}")
                    fig_open = True
                out.append(f"\\subsection*{{{inline_md(core)}}}")
            elif level == 2 and core.startswith(starred):
                out.append(f"\\section*{{{inline_md(core)}}}")
            elif level == 2 and re.match(r"^附录", plain):
                if not appendix_started:
                    out.append("\\appendix")
                    appendix_started = True
                out.append(f"\\section{{{inline_md(core)}}}")
            elif level == 2:
                out.append(f"\\section{{{inline_md(core)}}}")
            elif level == 3:
                out.append(f"\\subsection{{{inline_md(core)}}}")
            else:
                out.append(f"\\subsubsection{{{inline_md(core)}}}")
            i += 1
            continue
        if stripped.startswith("!["):
            flush_para()
            imgs = []
            while i < len(lines) and lines[i].strip().startswith("!["):
                pm = re.match(r"!\[[^\]]*\]\(([^)]+)\)", lines[i].strip())
                if pm:
                    imgs.append(pm.group(1))
                i += 1
            out.append("\\nopagebreak[4]")
            out.append("\\begin{center}")
            if len(imgs) == 1:
                out.append(f"\\includegraphics[width=0.9\\linewidth]{{{imgs[0]}}}")
            else:
                out.append("\\setlength{\\tabcolsep}{2pt}")
                out.append("\\begin{tabular}{cc}")
                for idx, img in enumerate(imgs):
                    cell = f"\\includegraphics[width=0.48\\linewidth]{{{img}}}"
                    last = idx == len(imgs) - 1
                    if idx % 2 == 0 and not last:
                        out.append(cell + " &")
                    else:
                        out.append(cell + r" \\")
                out.append("\\end{tabular}")
            out.append("\\end{center}")
            if fig_open:
                out.append("\\end{minipage}")
                fig_open = False
            continue
        if stripped.startswith("|"):
            flush_para()
            tbl_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl_lines.append(lines[i].strip())
                i += 1
            out.append(tex_table(tbl_lines))
            continue
        if stripped.startswith("> "):
            flush_para()
            out.append("\\begin{quote}")
            out.append(inline_md(stripped[2:]))
            out.append("\\end{quote}")
            i += 1
            continue
        om = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if om:
            flush_para()
            items = []
            while i < len(lines):
                im = re.match(r"^(\d+)\.\s+(.*)$", lines[i].strip())
                if not im:
                    break
                items.append(im.group(2))
                i += 1
            out.append("\\begin{enumerate}")
            for it in items:
                out.append(f"\\item {inline_md(it)}")
            out.append("\\end{enumerate}")
            continue
        if stripped.startswith("**Source:**"):
            flush_para()
            tag = stripped[len("**Source:**"):].strip()
            if re.match(r"p\.\d+\s+E\d+", tag):
                nm = re.search(r"Eq\.\s*\(([^)]+)\)", tag)
                pending_eq = nm.group(1) if nm else None
            else:
                pending_eq = None
                out.append("\\srctag{" + inline_md(tag) + "}")
            i += 1
            continue
        if stripped.startswith("**Placed near:**"):
            flush_para()
            i += 1
            continue
        mk = re.match(
            r"^\*\*(Original caption|Original|中文说明|中文图注|中文表注|中文|Reading note)[：:]?\*\*\s*(.*)$",
            stripped)
        if mk:
            flush_para()
            kind = mk.group(1)
            body = [mk.group(2)] if mk.group(2) else []
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if (not nxt or nxt.startswith("**") or nxt.startswith("<a id")
                        or nxt.startswith("#") or nxt == "$$" or nxt.startswith("![")
                        or nxt.startswith("|") or nxt.startswith("> ")
                        or re.match(r"^\d+\.\s", nxt)):
                    break
                body.append(nxt)
                i += 1
            text = inline_md(" ".join(body)) if body else ""
            if kind == "Original":
                out.append("\\begin{origpar}")
                out.append(text)
                out.append("\\end{origpar}\n")
            elif kind == "中文":
                out.append("\n" + text + "\n")
            elif kind == "中文说明":
                out.append("\\notepar{说明：" + text + "}\n")
            elif kind == "Reading note":
                out.append("\\notepar{精读提示：" + text + "}\n")
            else:
                out.append("\n" + text + "\n")
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        if stripped == "---":
            flush_para()
            out.append("\\bigskip")
            i += 1
            continue
        if stripped.startswith("- "):
            flush_para()
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append("\\begin{itemize}")
            for it in items:
                out.append(f"\\item {inline_md(it)}")
            out.append("\\end{itemize}")
            continue
        para_buf.append(stripped)
        i += 1
    flush_para()
    return "\n".join(out)


def render_document(body_tex: str, cfg: dict) -> str:
    return preamble(cfg) + "\n" + body_tex + "\n\\end{document}\n"


# ---------------------------------------------------------------- blocks

def parse_blocks(body: str) -> list[dict]:
    lines = body.splitlines()
    blocks: list[dict] = []
    i = 0
    current: dict | None = None
    while i < len(lines):
        line = lines[i]
        m = ANCHOR_RE.search(line)
        if m:
            if current:
                blocks.append(current)
            current = {"id": m.group(1), "kind": "paragraph", "page": None,
                       "source_tail": "", "original": [], "zh": [], "latex": None,
                       "images": []}
            i += 1
            continue
        if current is None:
            i += 1
            continue
        sm = SOURCE_LINE_RE.search(line)
        if sm and not current["page"]:
            current["page"] = int(sm.group(1))
            current["source_tail"] = sm.group(3).strip()
            if "Eq." in current["source_tail"]:
                current["kind"] = "equation"
            if "note" in current["source_tail"]:
                current["kind"] = "note"
            i += 1
            continue
        if line.strip() == "$$":
            j = i + 1
            math_lines: list[str] = []
            while j < len(lines) and lines[j].strip() != "$$":
                math_lines.append(lines[j])
                j += 1
            current["latex"] = "\n".join(math_lines).strip()
            current["kind"] = "equation"
            i = j + 1
            continue
        img = re.match(r"!\[[^\]]*\]\(([^)]+)\)", line.strip())
        if img:
            current["images"].append(img.group(1))
            i += 1
            continue
        if line.startswith("**Original:**"):
            current["original"].append(line[len("**Original:**"):].strip())
            i += 1
            continue
        zm = re.match(r"\*\*中文[：:]", line)
        if zm:
            current["zh"].append(line[zm.end():].strip().rstrip("*").strip())
            i += 1
            continue
        if line.startswith("### "):
            current.setdefault("heading", line[4:].strip())
        if line.strip() and not line.startswith("**"):
            if current["zh"]:
                current["zh"].append(line.strip())
            elif current["original"]:
                current["original"].append(line.strip())
        i += 1
    if current:
        blocks.append(current)
    return blocks


def clean_text(t: str) -> str:
    return t.replace("**", "").strip()
