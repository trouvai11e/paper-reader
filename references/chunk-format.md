# Chunk format contract

Every chunk file is a Markdown fragment; the assembler concatenates chunks in
manifest order. Do not write a title page, TOC, glossary, or formula index.

## Ids

| Prefix | Meaning |
|---|---|
| `S` | body paragraph |
| `E` | display equation (matches the paper's Eq. number) |
| `C` | figure/table caption |
| `F` | figure card |
| `T` | table |

Local ids are `S1-001`, `E1-001`, … (chunk number then reading order). The
assembler renumbers them globally to `S001`, `E001`, …. Use the local form only.

Each block starts with an anchor and a source line:

```
<a id="S1-003"></a>
**Source:** p.12 S1-003
```

Equation blocks add the paper's number:

```
<a id="E1-004"></a>
**Source:** p.12 E1-004 · Eq. (3.1)
```

## Paragraph block

```
<a id="S1-001"></a>
**Source:** p.1 S1-001

**Original:** The English sentence, with math in $...$.

**中文：** 忠实的中文翻译，保留术语与公式。
```

## Verbatim policy for the Original

The **Original must equal what the PDF page says** — character for character,
including the paper's own mistakes. Two distinct cases:

1. **OCR artifacts** (the MinerU dump disagrees with the PDF): clean them per
   the rules below; cleaning *restores* the paper. Record each in
   UNCERTAINTIES.
2. **The paper's own errors** (the PDF itself is wrong — a typo, a wrong
   symbol or exponent, a mis-cited equation): keep the Original verbatim,
   translate the *corrected* meaning in 中文, and add a `**校注：**` line:

```
**校注：** 原文作 $W^{1,1}$，依定理 2.1 的假设应为 $W^{1,p}$；译文按后者理解。
```

One sentence, after the 中文 of the block. The assembler collects every 校注
into `translation_notes.md`; `source_fidelity.py` reports any Original that
diverges from the dump beyond the OCR whitelist.

## OCR verification ladder

When a symbol or formula in the dump looks wrong, verify before recording:

1. **Text layer** (digital PDFs): `pdftotext -f <page> -l <page> -layout paper.pdf -`
   and compare; OCR often disagrees with the embedded text.
2. **Page image**: `pdftoppm -f <page> -l <page> -r 200 -png paper.pdf tmp/verify`
   (add `-x -y -W -H` to crop), then read the image visually.
3. **Still unsure** — and only then — add an `ASK:` line to UNCERTAINTIES:

```
- ASK: S1-008 p.12 — $W$ 的上标是 $1,1$ 还是 $1,p$？两级自验均无法区分。
```

The assembler collects all `ASK:` lines into a 待确认清单 in
`translation_notes.md`; `check_reader --stage assemble` fails while any
remain unresolved. After the user answers, write the fix into `ERRATA.json`
(with the basis in `reason`) and rewrite the line to
`- ASK(已解决): ... -> ERRATA <块id>`.

## Equation block

```
<a id="E1-001"></a>
**Source:** p.1 E1-001 · Eq. (1.1)

$$
\begin{cases}
u_t + f(u)_x = (A(u))_{xx} \\
u(x, 0) = u_0(x)
\end{cases}
$$

**中文说明：** 一句话说明公式的含义；不要重复公式本身。
```

Rules:

- The `$$` block contains cleaned LaTeX only; remove `\tag{...}` and record the
  number in the Source line.
- Unnumbered equations keep a Source line without `· Eq.`.
- Use `cases` for `\left\{\begin{array}{l}...\end{array}\right.`, `aligned` for
  multi-line derivations, `pmatrix`/`bmatrix` for matrices.
- One `中文说明` per equation; keep it to one sentence.

## Figure card

Place the card near the first substantive mention, not at the page bottom.

```
<a id="F1-001"></a>
### Fig. 1.1. 中文图题

**Placed near:** TBD-ANCHOR
**Source:** p.4 C1-001

![Fig. 1.1](assets/fig-1-1.png)

**Original caption:** Figure 1.1. The exact English caption.

**中文图注：** 图 1.1. 中文图注。

**Reading note:** 一句话说明这张图在论证中的作用。
```

- `TBD-ANCHOR` is replaced by the assembler with the nearest preceding `S`/`E` id.
- `assets/...` paths are relative to `reader/`.
- Use the stable `suggested_name` from `tmp/figures.json` (`fig-p5-b3.png`);
  semantic names such as `fig-1-1.png` are optional.
- Multi-panel figures use one `![...](...)` line per panel.

## Table block

```
<a id="T1-001"></a>
### Table 4.1. 中文表题

**Source:** p.22 T1-001

| k | N | $L^1$ error | $L^1$ rate |
|---|---|---|---|
| 1 | 20 | 5.78e-03 | |

**Original caption:** Table 4.1. The exact English caption.

**中文表注：** 表 4.1. 中文表注。
```

MinerU often flattens tables into one row; rebuild the header and rows by
splitting cells. Leave a missing rate blank.

Never drop a table or figure because it seems to belong to another section. Emit
it with a placement note and report the boundary in the closing message; the
inventory gate checks that every `Table N` / `Figure N` reaches `paper.md`.

## References

The bibliography is **not** translated by subagents: `gen_references.py`
generates those chunks deterministically right after planning (a
`## 参考文献（References）` heading, a one-line note that entries stay in
English, then an ordered list). If your chunk range borders the references
section, stop at its first line and report the boundary in the closing
message; never copy reference entries into your chunk.

## End of file

Every chunk ends with two sections:

```
UNCERTAINTIES:
- S1-008: OCR "0 . 0 1" cleaned to 0.01.
...

REPORT: S=17 E=9 C=1 F=1 T=28; new_terms=test function→试验函数, ...; boilerplate_lines_dropped=15; uncertainties=7
```

- Body prose is reader-facing: do **not** put `〔?〕` markers or `（OCR…）`
  commentary in the `Original` / `中文` / `中文说明` text. Record every doubt in
  UNCERTAINTIES with the block id and the source page.
- The assembler strips inline `〔?〕` in the default `ledger` mode; a marker is a
  fallback, not the primary record.
- `REPORT` counts must match the actual anchors in the file (`S=`, `E=`, `C=`,
  `F=`, `T=`). If the chunk stops early, add `next_line=<n>` and keep the counts
  accurate for what is written.
- `new_terms` uses `English→中文`; the assembler merges them into the ledger.

## OCR cleaning rules

Record every guess in UNCERTAINTIES with the block id; keep the body free of
proofreading commentary.

1. Remove spaces inside math: `\mathbb { R }` → `\mathbb{R}`; `1 . 2 ( \Delta x ) ^ { 2 }` → `1.2(\Delta x)^2`.
2. Compress multi-letter commands: `\operatorname* { m a x }` → `\operatorname*{max}`.
3. Drop `\tag{...}` from equations; keep the number in Source.
4. Convert `{ \alpha }` → `{\alpha}`; drop redundant braces.
5. `<sup>1</sup>` → `$L^1$`; same for `<sub>`.
6. Remove `\textstyle`/`\displaystyle` noise.
7. Remove stray `\left|` at line starts when it is not a norm.
8. Restore jump brackets `[\![\cdot]\!]` consistently; the assembler also
   normalizes `\llbracket`.
9. Fix dangling punctuation (`$u = 0 .$ .` → `$u = 0$`).
10. Keep English technical terms in the Chinese text on first use, e.g.
    `双重守恒（doubly conservative, DoC）`.

## Boilerplate to drop

Count the dropped lines for REPORT:

- running heads and journal headers;
- standalone page numbers;
- copyright/license lines ("Licensed to Fudan University…");
- `![Chart block](doc:...)` placeholders and standalone caption lines when the
  figure card already carries them;
- subfigure label lines that duplicate the card.

## Budget

- Read only your assigned line range; never re-read the whole paper.
- Stop at 250 output lines. At 80% of the budget, stop at a paragraph boundary
  and report `next_line` so the parent can re-dispatch the remainder.
