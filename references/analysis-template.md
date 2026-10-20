# 精读笔记 template

Write `reader/精读笔记.md` after the PDF is built. It is the analysis layer: the
PDF proves the text was translated; this file proves it was understood.

Rules:

- Chinese, 1500–2500 characters.
- Every non-obvious claim carries a `paper.md` block anchor, e.g.
  `[S031](paper.md#S031)`. Anchors are `S` (paragraph), `E` (equation),
  `F` (figure), `T` (table).
- Separate what the paper proves from what it observes numerically. Label the
  evidence strength.
- End with open questions, not a summary.

## Sections

1. **研究问题** — What question does the paper ask? What was the prior answer
   (the Lax–Wendroff theorem) and why does it fail here? Define the solution
   class the paper targets (weak vs ultra-weak).
2. **作者赌注** — The 2–3 load-bearing bets: what did the authors choose to
   strengthen or give up? What would falsify each bet?
3. **方法与定理链** — The chain: definitions → consistency → convergence
   theorem → concrete schemes → stability/accuracy. Name each theorem and its
   hypothesis.
4. **证明策略** — The actual moves, in order. For each key formula, say what it
   buys: summation by parts, Taylor expansion, compactness, inverse inequality.
5. **实验证据表** — A table: claim / figure or table / strength and caveats.
   Note rates that exceed the nominal order or drift with refinement.
6. **局限** — Assumptions that are not proved, missing uniqueness, semi-discrete
   only, dimension/grid coverage, numerical-vs-theorem gaps.
7. **可复用点** — What transfers: definition template, proof moves, stability
   trick, writing structure.
8. **待查问题** — 5–8 concrete questions a follow-up reader should resolve.
