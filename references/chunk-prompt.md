# Subagent prompt template

Fill the braces and dispatch one subagent per chunk. The subagent does not see
the parent conversation, so keep the prompt self-contained.

```
You are translating one chunk of an English paper into a bilingual reader.

## Paper
- Title: {title}
- Authors: {authors}
- Venue / DOI: {venue} / {doi}
- Source PDF: {source_pdf}
- MinerU parse: doc:{mineru_parse_id}, tier {tier}

## Your chunk
- Chunk id: {chunk_id}
- Section: {section_title}
- Input: `{mineru_path}` lines {line_start}–{line_end} (1-based, inclusive)
- Output: `{output_path}` (overwrite; no preamble, no summary)
- Assigned headings: {headings}
- Figure assets in range: {figures}   (from `tmp/figures.json`; use `suggested_name`)

## Read first
1. `{chunk_format_path}` — the block format contract. Follow it exactly.
2. `{glossary_path}` — terminology seed; use these translations.
3. Only the assigned line range of `{mineru_path}`; do not read the whole paper.
   Source pages come from the in-text `<!-- page N -->` markers, not the manifest.

## Write rules
- Write incrementally: create the file after the first 3 blocks, then append by
  editing. Do not buffer the whole chunk in memory and write at the end.
- Budget: stop at 250 output lines. At 80% of the budget, stop at a paragraph
  boundary and write `next_line=<n>` into the REPORT line before you stop; the
  parent will re-dispatch the remainder. Update the REPORT counts and `next_line`
  after roughly every 50 output lines, so a crash leaves a checkpoint.
- Keep the paper's math in LaTeX. Clean OCR noise only; do not rewrite math.
- The Original is verbatim: it must equal the PDF page, including the paper's
  own errors. A paper error stays in the Original, is corrected in the 中文,
  and gets a one-sentence `**校注：**` line.
- Doubtful OCR: verify with the pdftotext text layer first, then a pdftoppm
  page image; if still unsure, record `- ASK: <block> p.<n> — <question>` in
  UNCERTAINTIES instead of guessing.
- Translate faithfully; do not summarize, merge, or "improve" proofs.
- Keep English technical terms on first use, e.g. `双重守恒（doubly conservative, DoC）`.
- Body prose is reader-facing: no `〔?〕` markers and no `（OCR…）` commentary in
  the `Original` / `中文` / `中文说明` lines. Record every doubt in UNCERTAINTIES
  with the block id and source page.
- Never drop a table or figure because it seems to belong to another section;
  emit it with a placement note.
- Drop boilerplate (running heads, page numbers, license lines, chart-block
  placeholders) and count the dropped lines.
- Section headings: promote `x.y.` to `###` and `x.y.z.` to `####`, bilingual
  `中文（English）`. Every heading in `Assigned headings` must appear as a heading.
- REPORT counts must match the anchors you actually wrote.

## End of file
```
UNCERTAINTIES:
- ...

REPORT: S=.. E=.. C=.. F=.. T=..; new_terms=English→中文, ...; boilerplate_lines_dropped=..; uncertainties=..
```

## Closing message
Reply only with the output path and the REPORT line. If you stopped early, add
`next_line=<n>`.
```
