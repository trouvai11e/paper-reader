# paper-reader

A repeatable pipeline for turning one English paper into a bilingual reader:
`paper.md` + `source_map.json` + `reader.tex` + `reader.pdf` + `精读笔记.md`.

## Install

Copy this folder to `~/.agents/skills/paper-reader/`. The scripts are stdlib-only
and run with `uv run`. The LaTeX class is bundled verbatim at
`TeXTemplate/elegantnote.cls` (ElegantNote v2.70, LPPL 1.3c, from
github.com/ElegantLaTeX/ElegantNote); `--template` can point elsewhere.

## Quick start

```powershell
# 1. config + preflight
uv run scripts/init_config.py --pdf paper.pdf --title "..." --authors "..." --doi "..." --out reader.config.json
$env:UV_CACHE_DIR="$PWD/tmp/uv-cache"
uv run scripts/preflight.py --template TeXTemplate/elegantnote.cls

# 2. parse + plan
uv run scripts/parse_paper.py --pdf paper.pdf --out tmp/mineru_full.md --assets reader/assets
# fill tmp/headings.json (numeric headings with en/zh; level-2 line numbers
# drive the section-first split; include the References heading)
uv run scripts/plan_chunks.py --mineru tmp/mineru_full.md --out tmp/chunk_manifest.json --target-out 220 --max-lines 300 --headings tmp/headings.json
uv run scripts/inventory.py --mineru tmp/mineru_full.md --out tmp/inventory.json
# references chunks are generated deterministically, no subagent
uv run scripts/gen_references.py --config reader.config.json --mineru tmp/mineru_full.md

# 3. translate chunks section by section (chunk_state.py next lists the
# dispatchable chunks of the earliest unfinished section; see
# references/chunk-prompt.md)
uv run scripts/chunk_state.py --config reader.config.json status
uv run scripts/chunk_state.py --config reader.config.json next

# 4. assemble + check + build
uv run scripts/assemble.py --config reader.config.json
uv run scripts/build_reader.py --config reader.config.json
uv run scripts/check_reader.py --config reader.config.json --stage all
# report-only: does any Original diverge from the dump beyond OCR cleaning?
uv run scripts/source_fidelity.py --config reader.config.json --mineru tmp/mineru_full.md

# 5. rebuild without LLM (after paper.md is committed)
uv run scripts/md2tex.py --config reader.config.json
```

## Scripts

| Script | Role |
|---|---|
| `preflight.py` | tools, uv cache, MinerU server, font test |
| `init_config.py` | create `reader.config.json` + `reader/` |
| `parse_paper.py` | MinerU parse + `parse_meta.json` + figure inventory |
| `plan_chunks.py` | section-first manifest: ranges, est_out, pages, headings, kind |
| `inventory.py` | table/figure caption inventory |
| `gen_references.py` | deterministic references chunks (entries stay English) |
| `chunk_state.py` | sync/status/next; `next` stays inside the earliest unfinished section |
| `assemble.py` | chunks → `paper.md`, `source_map.json`, `translation_notes.md` |
| `md2tex.py` | `paper.md` → `reader.tex` (rebuild path) |
| `build_reader.py` | md2tex + xelatex ×2 + font/page gates |
| `check_reader.py` | chunk state, heading, inventory, fidelity, hygiene, ASK/errata, LaTeX, font gates |
| `source_fidelity.py` | report-only: Original blocks vs the dump (OCR whitelist) |
| `accent_audit.py` | list `\dot`/`\hat`/… for a source spot-check |
| `selftest.py` | converter/planner/state unit tests |

## Gates

1. Chunk state: every chunk `done`; REPORT counts match; `next_line` only on partial;
   references chunks report `refs=` equal to the listed entry count.
2. Manifest covers `1..total_lines`, no missing chunk.
3. Heading inventory present with the declared level.
4. Every table/figure in `tmp/inventory.json` is in `paper.md`.
5. Unique ids; `source_map.json` blocks == anchors.
6. Text fidelity: `source_map` text appears in both `paper.md` and `reader.tex`.
7. No `〔?〕` or CJK-in-inline-math in the body; errata applied, each with a `reason`.
8. No unresolved `ASK:` items (`--allow-pending` exempts); zero LaTeX errors;
   `FZ` fonts; PDF/log newer than their sources.
9. Page count sane; five pages visually checked; accent audit done.
10. `--stage source` (report-only): Originals match the dump modulo the OCR
    whitelist.

See `SKILL.md` for the phase-by-phase workflow, and `references/` for the chunk
format, layout rules, subagent prompt, and analysis template.
