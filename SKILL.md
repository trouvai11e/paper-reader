---
name: paper-reader
description: Build a source-grounded bilingual paper reader (paper.md + source_map.json + LaTeX/PDF + optional 精读笔记) with repeatable chunk planning, fail-fast gates, and a PDF review loop. Use only when the user asks for a rebuildable bilingual reader/PDF (双语对照 reader、翻译论文并排版、把论文做成 PDF、paper reader) or continues an existing reader project. Not for a quick 精读/讲透 (use nature-paper-xray), a 精读卡 (use nature-paper-card), or a plain text translation (use nature-reader).
---

# Paper Reader

Turn one English paper into a bilingual reading edition whose PDF can be rebuilt
from committed sources. The pipeline is: **plan → translate → assemble → build → review**.

## Outputs

| File | Role |
|---|---|
| `reader/paper.md` | Bilingual body, block ids `S/E/C/F/T` |
| `reader/source_map.json` | Block → page/original/translation/equation |
| `reader/translation_notes.md` | OCR uncertainties, new terms, chunk reports |
| `reader/reader.tex` | Generated from `paper.md`; never hand-edit |
| `reader/reader.pdf` | Deliverable |
| `reader/assets/` | Cropped figures |
| `reader/ERRATA.json` | Durable manual corrections (block, old, new) |
| `reader/精读笔记.md` | Optional analysis layer (not in the PDF) |

`paper.md` is the rebuild source. `tmp/chunks/` stays out of git; `md2tex.py`
rebuilds `reader.tex` from `paper.md` without any LLM call.

## Setup (once per project)

1. `uv run scripts/init_config.py --pdf <pdf> --title "..." --authors "..." --doi "..." --out reader.config.json`
   fills `reader.config.json` and creates `reader/`.
2. Set `$env:UV_CACHE_DIR="$PWD/tmp/uv-cache"` for every `uv run` on Windows; the
   default cache under `%LOCALAPPDATA%` is denied by the workspace sandbox.
3. `uv run scripts/preflight.py --start-server`
   checks tools, the uv cache, the MinerU server (`mineru server start` needs
   `~/.mineru` write access; exit code 2 means an approval/permission issue,
   1 means a fixable failure), and the `chinesefont=founder` font gate. The
   bundled `TeXTemplate/elegantnote.cls` is the default template.
4. `git init`; set `user.name` / `user.email`.

**Do not enter Phase 1 while preflight fails** — parsing without a running
MinerU server wastes an approval round and produces nothing.

Completion: preflight exits 0 (or only warns); config exists.

## Working rules (learned the hard way)

- Never poll subagents with sleeps; the harness notifies you when each
  finishes. Never read or edit a chunk file while its subagent is running —
  that is a race and has corrupted chunks before.
- Manual corrections to translated text go **only** into `reader/ERRATA.json`
  (with `reason`); never edit a chunk file's prose by hand.
- Ad-hoc fix scripts belong in `tmp/` and must verify their effect (re-read
  the target region) before rebuilding.

## Phase 1 — Parse and plan

1. `uv run scripts/parse_paper.py --pdf <pdf> --out tmp/mineru_full.md --assets reader/assets --config reader.config.json`
   writes `tmp/parse_meta.json` (`doc`, `tier`, `pages`, `figures`, `lines`)
   and backfills `mineru_parse_id` / `mineru_tier` / `pages` into the config.
2. Build `tmp/headings.json`: every numeric heading (`3`, `3.1`, `3.3.1`) with
   `level`, `en`, `zh`, and `line` (`level` 2 = section, 3 = subsection, 4 =
   subsubsection). The planner uses the level-2 headings as section split
   points, so their `line` fields must be accurate. MinerU sometimes emits
   `## 6.1` subsections and sometimes leaves them buried as `3.1. ...`;
   inventory what the dump actually has. Include the bibliography heading
   (`References`) even if unnumbered, so the planner can mark it.
3. `uv run scripts/plan_chunks.py --mineru tmp/mineru_full.md --out tmp/chunk_manifest.json --target-out 220 --max-lines 300 --headings tmp/headings.json`
   splits section-first, then packs each section by estimated output size
   (`1.1*text + 3.5*display`). Cut points prefer blank lines and numbered
   subsection headings and never land inside a display-math block. The
   bibliography section becomes a single `kind: "references"` chunk (never
   split — it is script-generated, so no output budget applies). The planner
   warns about over-budget chunks and about numeric-looking headings in the
   dump that are missing from `tmp/headings.json`: **fix the inventory and
   replan when the reconciliation warns**, a missed section breaks the split.
4. `uv run scripts/inventory.py --mineru tmp/mineru_full.md --out tmp/inventory.json`
5. `uv run scripts/gen_references.py --config reader.config.json --mineru tmp/mineru_full.md`
   generates the references chunks deterministically (entries stay in English;
   wrapped lines are merged, entries renumbered; doubts go to UNCERTAINTIES).
   No translation subagent is ever dispatched for them.
6. Review the manifest: line ranges cover `1..total_lines`; each `est_out` ≤220;
   every heading assigned to exactly one chunk; the references section is
   marked `kind: "references"`.

Completion: line coverage holds, each chunk has an `est_out`, the table/figure
inventory is written, and references chunks are `done`.

## Phase 2 — Translate chunks, section by section

- Sections are translated in order; chunks within one section may run in
  parallel (at most `pipeline.max_agents`, default 4). This keeps the
  terminology ledger growing monotonically. After each section completes, run
  `uv run scripts/merge_terms.py --config reader.config.json` to aggregate the
  chunks' `new_terms` into the seed before dispatching the next section.
- `uv run scripts/chunk_state.py --config reader.config.json next` prints the
  dispatchable chunks: partials first, then planned, but only inside the
  earliest unfinished section. `kind: "references"` chunks are never
  dispatched (gen_references.py already wrote them).
- Fill `references/chunk-prompt.md`; pass the chunk's line range, assigned
  headings, terminology seed, and output path.
- Budget: stop at 250 output lines. At 80% of the budget, stop at a paragraph
  boundary and report `next_line`; do not write past the budget.
- The Original is verbatim: it must equal the PDF page, including the paper's
  own errors. Clean only OCR artifacts; a paper error stays in the Original,
  is corrected in the 中文, and gets a `**校注：**` line. See
  `references/chunk-format.md` ("Verbatim policy").
- Doubtful OCR: run the verification ladder (pdftotext text layer, then a
  pdftoppm page image) before recording; if still unsure, write `- ASK: ...`
  in UNCERTAINTIES instead of guessing. All ASK items are collected into
  `translation_notes.md` and presented to the user once, before assembly.
- Body prose is reader-facing: no `〔?〕` markers and no `（OCR…）` commentary.
  Record every doubt in `UNCERTAINTIES:` with the block id. The assembler strips
  inline markers in the default `ledger` mode.
- The subagent writes only its chunk file, then reports `REPORT:` and
  `UNCERTAINTIES:` at the end. REPORT counts must match the block anchors.
- After each completion, run `uv run scripts/chunk_state.py --config reader.config.json sync`.
  It records `status`, `next_line`, and `counts` in the manifest. `status` is
  the resume table after a limit or crash.
- A chunk that stops early is `partial` with `next_line`; split a remainder over
  120 input lines into two before dispatching again.

Completion: `chunk_state.py status` shows every chunk `done`; every assigned
heading appears as a real `###`/`####` heading.

## Phase 3 — Assemble

Before assembling, present every `ASK:` item from `translation_notes.md`'s
待确认清单 to the user (page + cropped image); record answers in
`reader/ERRATA.json` with the basis in `reason` and rewrite the ASK line to
`- ASK(已解决): ... -> ERRATA <块id>`.

```
uv run scripts/chunk_state.py --config reader.config.json status
uv run scripts/assemble.py --config reader.config.json
uv run scripts/check_reader.py --config reader.config.json --stage chunks
uv run scripts/check_reader.py --config reader.config.json --stage assemble
uv run scripts/check_reader.py --config reader.config.json --stage source
```

The assembler refuses a `partial`, `planned`, or `failed` chunk; it orders chunks
by manifest, applies `reader/ERRATA.json`, renumbers block ids globally, promotes
buried section headings, strips inline markers in `ledger` mode, and writes
`paper.md` / `source_map.json` / `translation_notes.md` (with 校注汇总 and
待确认清单 sections).

Manual fixes to the text go into `reader/ERRATA.json` as
`{"block": "S007", "old": "...", "new": "...", "reason": "..."}`. `reason` is
mandatory: state the basis (e.g. "p.12 作者确认为 $u_0$"). Fixes to the English
Original are allowed only to restore PDF fidelity, never to improve the paper.
Do not edit `paper.md` directly: a re-assembly would overwrite it, and the fix
would be lost.

Completion: `--stage chunks` and `--stage assemble` both pass, including text
fidelity and the table/figure inventory; `--stage source` (report-only) lists
no unexplained divergences.

## Phase 4 — Build

```
uv run scripts/build_reader.py --config reader.config.json
uv run scripts/check_reader.py --config reader.config.json --stage build
uv run scripts/accent_audit.py --paper reader/paper.md
```

Gates: zero `!` errors in `reader.log`, `pdffonts` contains `FZ`, page count sane,
`reader.pdf` and `reader.log` newer than `paper.md`/`reader.tex`. Render five pages
and read them: title, abstract, a heavy equation page, a figure page, a table page.

Run the accent audit and compare each `\dot`/`\hat`/`\bar`/`\tilde`/`\widehat`/
`\overline`/`\underline` with the cited PDF page; OCR often adds or drops accents
(for example `W^{1,1}` read as `\dot{W}^{1,1}`).

Completion: all gates pass; the five pages look correct.

## Phase 5 — Review and deliver

- Layout changes: worktree `reader/layout-polish`, rebuild, user reviews the PDF,
  then fast-forward merge. Content fixes may commit directly once the user has
  approved the PDF.
- Analysis layer: follow `references/analysis-template.md` and write
  `reader/精读笔记.md` with `paper.md` block anchors.
- Write `reader/README.md`: one rebuild command + dependencies.
- Commit `reader.pdf`, `paper.md`, `source_map.json`, `translation_notes.md`,
  `reader.tex`, `reader/ERRATA.json`, `reader.config.json`, `assets/`.

Completion: `git status` clean; a fresh clone can rebuild the PDF from `paper.md`.

## Gates (`check_reader.py`)

1. Chunk state: every chunk `done`; REPORT counts match anchors; `next_line` only
   on a `partial` chunk; references chunks report `refs=` equal to the listed
   entry count.
2. Manifest coverage and chunk files (no gaps, no missing chunks).
3. Heading inventory present with the declared level; unnumbered headings
   (Abstract, References, …) match by title text.
4. Every table/figure in `tmp/inventory.json` appears as a heading in `paper.md`.
5. Unique ids; `source_map.json` block count equals anchor count; no `TBD`
   placeholder survives into `paper.md`.
6. Text fidelity: every `source_map` block's original/translation is present in
   both `paper.md` and `reader.tex` (catches dropped paragraphs).
7. Body hygiene: no `〔?〕`, no CJK inside inline math; OCR commentary warns.
8. Errata applied, each with a `reason`; no unresolved `ASK:` items
   (`--allow-pending` exempts); zero LaTeX errors; `FZ` font; PDF/log newer
   than their sources.
9. Page count reported; five-page visual check + accent audit done by the agent.
10. Source fidelity (`--stage source`): **fails** when page resolution is
    broken (>50% of blocks without a source page — that means source_map is
    silently destroyed); per-block text divergence stays report-only.

`--stage status` prints the per-chunk state table and exits 1 if anything is not
`done`; that is the resume command after a session limit.

## Pointers

- Block format, ids, OCR rules, boilerplate list → `references/chunk-format.md`
- PDF layout rules (title, `[p.x Snnn]`, `\tag`, captions) → `references/layout-spec.md`
- Subagent prompt template → `references/chunk-prompt.md`
- Deterministic references generation → `scripts/gen_references.py`
- Analysis-note sections → `references/analysis-template.md`
- Config schema → `references/config.example.json`
