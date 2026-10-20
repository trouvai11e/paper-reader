# Layout spec (bilingual reader PDF)

This is the design settled on the YCLS2026MC reader and modeled on the
Quenjel2020 reader. The assembler emits it; do not hand-edit `reader.tex`.

## Document class

```latex
\documentclass[cn,normal,blue,12pt,chinesefont=founder]{elegantnote}
```

- `device=normal` (A4), `blue`, `12pt`.
- `chinesefont=founder` is explicit. The class default is `ctexfont`; a PDF
  without `FZ*` fonts in `pdffonts` is a failure, even if it compiles.
- `math=cm` is the default; keep it unless the user asks otherwise.

## Title block

```latex
\title{English Title（中文译名）}
\author{Original authors}
\institute{Journal (Publisher)}
\date{\today}
```

- Title: English original, Chinese translation in full-width parentheses, same
  font size (single `\title` line).
- Authors: the paper's authors, not the reader's name.
- `\institute`: journal, not the DOI.

Below `\maketitle`, a gray small block:

```
Journal, DOI: 10.xxxx/xxxx          <- \href, clickable
2020 Mathematics Subject Classification: ...
Keywords: ...
本笔记为个人精读对照版，原文版权归 … 所有，请勿公开再分发。
\hrule
```

No version line, no TOC, no page index, no formula index, no glossary in the
PDF. The terminology ledger lives in `translation_notes.md` / `source_map.json`.

## Body

Every block:

1. `\hypertarget{S001}{}` — anchor.
2. `\srctag{p.12 S001}` — right-aligned gray `[p.12 S001]`, no "Source:" prefix.
3. `\begin{origpar} English \end{origpar}` — `\small`, `black!65`, no label.
4. Chinese paragraph — normal black, no label.

Equation blocks:

```latex
\begin{equation}
...
\tag{3.1}
\end{equation}
```

- Numbered equations use `\tag{n.m}` at the right margin.
- Unnumbered equations use `\[ ... \]`.
- Display equations carry no `[p.x Ennn]` source line on the page. The block id
  still exists in `source_map.json` and as `\hypertarget`.

Reader-added notes:

- `\notepar{说明：…}` — one sentence explaining an equation.
- `\notepar{校注：…}` — the paper's own error: Original stays verbatim, the
  note states what is wrong and what the translation assumes.
- `\notepar{精读提示：…}` — a reading hint; small gray italic.

## Figures and tables

- Figure/table heading is a bold `\subsection*` line:
  `Fig. 4.1. English caption（中文图注）`.
- Keep the paper's own numbering (`Fig. 4.1`, `Table 4.1`); do not use LaTeX
  `figure`/`table` floats, which would renumber them.
- Images: `\includegraphics[width=0.9\linewidth]`; multi-panel uses a two-column
  `tabular` with `0.48\linewidth` cells.
- Tables use `longtable` + `booktabs`; `\arraystretch{1.25}`.
- Captions are merged into the heading; do not emit separate
  `Original caption:` / `中文图注：` lines in the PDF.
- `\nopagebreak[4]` before each figure to keep the caption with the image.

## Section headings

- Section: `\section{中文（English）}`; auto-numbered.
- Subsection: `\subsection{中文（English）}`.
- Subsubsection: `\subsubsection{中文（English）}`.
- Appendix: `\appendix` then `\section{中文（English）}`.
- References: `\section*{参考文献（References）}`.

Chinese first, English in full-width parentheses, matching the paper's existing
style. Do not copy another reader's heading wording.

## Page checks

Render and read five pages before delivery:

1. title page — title, authors, gray header, `[p.1 S001]`;
2. abstract page — original/Chinese contrast;
3. heavy equation page — `\tag` at the right margin, no overflow;
4. figure page — caption `English（中文）`, image visible;
5. table page — header repeats, no clipped columns.
