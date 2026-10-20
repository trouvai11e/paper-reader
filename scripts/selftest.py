#!/usr/bin/env python3
"""Selftest for the paper-reader converter and gates.

Usage: uv run selftest.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_references
import merge_terms
import plan_chunks
import source_fidelity
from readerlib import (
    PAGE_MARKER_RE,
    caption_inventory,
    collect_emendations,
    dispatchable,
    effective_status,
    esc_outside_math,
    fidelity_missing,
    inline_md,
    is_references_heading,
    math_mask,
    md_to_tex,
    merge_captions,
    parse_blocks,
    pending_asks,
    promote_headings,
    renumber,
    resolve_template,
    split_heading_sentence,
    strip_uncertainty_markers,
)


class InlineMdTest(unittest.TestCase):
    def test_math_comparisons_survive(self) -> None:
        out = inline_md("$a<b$ and $c>d$")
        self.assertIn("a<b", out)
        self.assertIn("c>d", out)

    def test_math_comparisons_without_spaces_survive(self) -> None:
        out = inline_md("$0=t_0<t_1<\\cdots$ and $c_0>0$")
        self.assertIn("t_1", out)
        self.assertIn("c_0", out)

    def test_known_tags_stripped(self) -> None:
        self.assertEqual(inline_md("<span>x</span>"), "x")
        self.assertEqual(inline_md("<sup>1</sup>"), "$^{1}$")
        self.assertEqual(inline_md("<sub>i</sub>"), "$_{i}$")


class MarkerTest(unittest.TestCase):
    def test_math_then_cjk_keeps_space(self) -> None:
        out, n = strip_uncertainty_markers("$X$〔?〕汉字")
        self.assertEqual(n, 1)
        self.assertEqual(out, "$X$ 汉字")

    def test_plain_removal(self) -> None:
        out, n = strip_uncertainty_markers("a〔?〕b")
        self.assertEqual((out, n), ("ab", 1))

    def test_before_punctuation(self) -> None:
        out, _ = strip_uncertainty_markers("中文〔?〕，后")
        self.assertEqual(out, "中文，后")


class HeadingTest(unittest.TestCase):
    def test_split_heading_sentence_bold(self) -> None:
        got = split_heading_sentence("3.1. **Doubly conservative schemes.** Since the...")
        self.assertEqual(got, ("3.1", "Doubly conservative schemes", "Since the..."))

    def test_split_heading_sentence_plain(self) -> None:
        got = split_heading_sentence("3.3.1. Doubly conservative finite difference method. This...")
        self.assertEqual(got[0], "3.3.1")
        self.assertEqual(got[2], "This...")

    def test_promote_headings(self) -> None:
        body = (
            '<a id="S001"></a>\n**Source:** p.13 S001\n\n'
            "**Original:** 3.1. Doubly conservative schemes. Since the convective term.\n\n"
            "**中文：** 3.1. 双重守恒格式。由于对流项。\n"
        )
        inv = {"headings": [{"num": "3.1", "level": 3,
                             "en": "Doubly conservative schemes", "zh": "双重守恒格式"}]}
        out = promote_headings(body, inv)
        self.assertIn("### 3.1 双重守恒格式（Doubly conservative schemes）", out)
        self.assertIn("**Original:** Since the convective term.", out)
        self.assertIn("**中文：** 由于对流项。", out)


class RenumberTest(unittest.TestCase):
    def test_mapping_and_references(self) -> None:
        body, mapping = renumber(['<a id="S1-001"></a>\n**Source:** p.1 S1-001'])
        self.assertIn('<a id="S001"></a>', body)
        self.assertIn("p.1 S001", body)
        self.assertEqual(mapping["S1-001"], "S001")


class CaptionTest(unittest.TestCase):
    def test_merge_captions(self) -> None:
        block = (
            '<a id="F001"></a>\n### Fig. 1.1. 中文图题\n\n'
            "**Source:** p.4 C1-001\n\n![Fig. 1.1](assets/fig-1-1.png)\n\n"
            "**Original caption:** Figure 1.1. The comparison\n\n"
            "**中文图注：** 图 1.1. 对比。\n"
        )
        out = merge_captions(block)
        self.assertIn("### Fig. 1.1. The comparison（对比）", out)

    def test_inventory(self) -> None:
        items = caption_inventory("Table 4.1. Accuracy table\nFigure 1.1. Comparison")
        self.assertEqual(len(items), 2)
        self.assertEqual({i["kind"] for i in items}, {"table", "figure"})


class FidelityTest(unittest.TestCase):
    BLOCK = {
        "id": "S001",
        "type": "paragraph",
        "original_text": "This is a long enough English sentence with several words to form shingles.",
        "translation": "这是一个足够长的中文段落，用来测试保真检查是否能发现整段缺失。",
    }

    def test_full_text_passes(self) -> None:
        tex = ("\\begin{origpar}This is a long enough English sentence with several words "
               "to form shingles.\\end{origpar} 这是一个足够长的中文段落，用来测试保真检查是否能发现整段缺失。")
        self.assertEqual(fidelity_missing([self.BLOCK], tex), [])

    def test_truncated_text_fails(self) -> None:
        tex = "This is a long enough English sentence"
        self.assertEqual(fidelity_missing([self.BLOCK], tex), ["S001"])


class PlannerTest(unittest.TestCase):
    LINES = [f"text line {i}" for i in range(1, 81)]

    def test_density_increases_estimate(self) -> None:
        plain = plan_chunks.estimate_out(self.LINES, 1, 20)
        with_math = list(self.LINES)
        with_math[5] = "$$"
        with_math[6] = "x = y"
        with_math[7] = "$$"
        self.assertGreater(plan_chunks.estimate_out(with_math, 1, 20), plain)

    def test_split_covers_range(self) -> None:
        ranges = plan_chunks.split_section(self.LINES, 1, len(self.LINES), 300, 60)
        self.assertEqual(ranges[0][0], 1)
        self.assertEqual(ranges[-1][1], len(self.LINES))
        for (a, b), (c, _d) in zip(ranges, ranges[1:]):
            self.assertEqual(b + 1, c)
            self.assertLessEqual(b - a + 1, 300)

    def test_never_cuts_inside_display_math(self) -> None:
        # 30 text lines, then a 6-line display block straddling the budget,
        # then more text. target_out forces the cut inside the math block;
        # the planner must back off to the last line before `$$`.
        lines = [f"text line {i}" for i in range(1, 31)]
        lines += ["$$", "a = b", "c = d", "e = f", "g = h", "$$"]
        lines += [f"tail line {i}" for i in range(1, 21)]
        ranges = plan_chunks.split_section(lines, 1, len(lines), 300, 40)
        mask = math_mask(lines)
        for a, b in ranges:
            self.assertFalse(mask[b - 1], f"chunk ends inside math at line {b}")
        self.assertEqual(ranges[0], (1, 30))
        self.assertEqual(ranges[-1][1], len(lines))

    def test_section_bounds_from_inventory(self) -> None:
        lines = [f"line {i}" for i in range(1, 201)]
        inv = [
            {"num": "1", "level": 2, "line": 1, "en": "Introduction"},
            {"num": "2", "level": 2, "line": 50, "en": "Main results"},
            {"num": "2.1", "level": 3, "line": 60, "en": "Setup"},
            {"num": "R", "level": 2, "line": 190, "en": "References"},
        ]
        bounds = plan_chunks.section_bounds(lines, 40, inv)
        # The 11-line references section stays standalone (never merged away).
        self.assertEqual(bounds[-1], (190, 200, "References"))
        self.assertEqual(bounds[0][0], 1)
        self.assertEqual(bounds[1][0], 50)
        # Level-3 headings are not section split points.
        self.assertFalse(any(s == 60 for s, _e, _t in bounds))

    def test_references_heading_detection(self) -> None:
        self.assertTrue(is_references_heading("References"))
        self.assertTrue(is_references_heading("参考文献"))
        self.assertFalse(is_references_heading("Main results"))


class DispatchTest(unittest.TestCase):
    def _row(self, cid, start, end, section, status="planned", kind="translate"):
        return {"status": status, "next_line": None,
                "chunk": {"id": cid, "line_start": start, "line_end": end,
                          "section": section, "kind": kind}}

    def test_stays_in_earliest_section(self) -> None:
        rows = [self._row("c01", 1, 50, 1), self._row("c02", 51, 100, 1),
                self._row("c03", 101, 150, 2)]
        got = dispatchable(rows, 4)
        self.assertEqual([r["chunk"]["id"] for r in got], ["c01", "c02"])

    def test_partial_before_planned(self) -> None:
        rows = [self._row("c01", 1, 50, 1, status="done"),
                self._row("c02", 51, 100, 2),
                self._row("c03", 101, 150, 2, status="partial")]
        got = dispatchable(rows, 4)
        self.assertEqual([r["chunk"]["id"] for r in got], ["c03", "c02"])

    def test_references_never_dispatched(self) -> None:
        rows = [self._row("c01", 1, 50, 1, status="done"),
                self._row("c02", 51, 80, 2, kind="references")]
        self.assertEqual(dispatchable(rows, 4), [])

    def test_legacy_manifest_without_section(self) -> None:
        row = self._row("c01", 1, 50, 1)
        del row["chunk"]["section"]
        rows = [row, self._row("c02", 51, 100, 2)]
        del rows[1]["chunk"]["section"]
        self.assertEqual(len(dispatchable(rows, 4)), 2)


class GenReferencesTest(unittest.TestCase):
    LINES = [
        "## References",
        "[1] A. Author, Title one,",
        "J. Math 1 (2020), 1--10.",
        "[2] B. Author. Title two. DOI: 10. 1234/abc",
        "42",
        "[3] C.",
    ]

    def test_entries_merged_and_cleaned(self) -> None:
        entries, uncertainties, dropped = gen_references.parse_entries(
            self.LINES, 1, len(self.LINES))
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0],
                         "A. Author, Title one, J. Math 1 (2020), 1--10.")
        self.assertIn("10.1234/abc", entries[1])
        self.assertEqual(dropped, 2)  # heading + page number
        self.assertTrue(any("entry 3" in u for u in uncertainties))

    def test_render_chunk_report_matches_entries(self) -> None:
        entries, uncertainties, dropped = gen_references.parse_entries(
            self.LINES, 1, len(self.LINES))
        text = gen_references.render_chunk("## 参考文献（References）",
                                           entries, uncertainties, dropped)
        self.assertIn("REPORT: S=0 E=0", text)
        self.assertIn("refs=3", text)
        # The generated file passes the chunk state machine as done.
        tmp = Path("tmp/_selftest")
        tmp.mkdir(parents=True, exist_ok=True)
        p = tmp / "c99.md"
        p.write_text(text, encoding="utf-8")
        self.assertEqual(effective_status(p)[0], "done")

    def test_numbered_references_title(self) -> None:
        inv = {"headings": [{"num": "7", "level": 2, "en": "References"}]}
        self.assertEqual(gen_references.references_title(inv),
                         "## 7. 参考文献（References）")
        self.assertEqual(gen_references.references_title({"headings": []}),
                         "## 参考文献（References）")


class VerbatimTest(unittest.TestCase):
    def test_emendation_renders_as_notepar(self) -> None:
        md = ("**校注：** 原文作 $W^{1,1}$，应为 $W^{1,p}$。\n")
        tex = md_to_tex(md, {})
        self.assertIn("\\notepar{校注：原文作 $W^{1,1}$，应为 $W^{1,p}$。}", tex)

    def test_collect_emendations_with_block_id(self) -> None:
        body = ('<a id="S007"></a>\n**Source:** p.3 S007\n\n'
                "**Original:** verbatim.\n\n**中文：** 译文。\n\n"
                "**校注：** 原文符号有误。\n")
        self.assertEqual(collect_emendations(body), ["- S007: 原文符号有误。"])

    def test_pending_asks_open_and_resolved(self) -> None:
        tails = {"c01:uncertainties":
                 "\nUNCERTAINTIES:\n- ASK: S1-008 p.12 — 上标是 1,1 还是 1,p？\n"
                 "- ASK(已解决): S1-003 p.2 — 已确认 -> ERRATA S003\n"}
        asks = pending_asks(tails)
        self.assertEqual(len(asks), 1)
        self.assertIn("S1-008", asks[0])

    def test_normalize_tokens_whitelists_ocr_noise(self) -> None:
        dump = "The space $\\mathbb { R }$ with <sup>1</sup> \\tag{3.1} end"
        original = "The space $\\mathbb{R}$ with $^1$ end"
        self.assertEqual(source_fidelity.normalize_tokens(dump),
                         source_fidelity.normalize_tokens(original))

    def test_divergence_beyond_whitelist_detected(self) -> None:
        lines = ["<!-- page 3 -->", "The kernel estimate holds for all u."]
        blocks = [{"id": "S001", "page": 3, "kind": "paragraph",
                   "original": ["The kernel estimate holds for all v."],
                   "zh": [], "latex": None, "images": []}]
        pages = source_fidelity.page_tokens(lines)
        self.assertEqual(source_fidelity.divergent_blocks(blocks, pages),
                         [("S001", 3, "original")])

    def test_bundled_template_resolves(self) -> None:
        p = resolve_template("TeXTemplate/elegantnote.cls")
        self.assertTrue(str(p).replace("\\", "/").endswith("elegantnote.cls"))
        bundled = resolve_template("TeXTemplate/elegantnote.cls",
                                   base=Path("nonexistent-dir"))
        self.assertTrue(bundled.exists())  # falls back to the skill copy


class ContractRegressionTest(unittest.TestCase):
    """Regression tests for the defects found in the arxiv-2610.20133 run."""

    def test_page_marker_accepts_both_forms(self) -> None:
        self.assertEqual(PAGE_MARKER_RE.search("<!-- page 12 -->").group(1), "12")
        self.assertEqual(PAGE_MARKER_RE.search("<!-- page 12 of 27 -->").group(1), "12")

    def test_source_line_accepts_global_ids(self) -> None:
        blocks = parse_blocks('<a id="S012"></a>\n**Source:** p.7 S012\n\n'
                              "**Original:** Text.\n\n**中文：** 文。\n")
        self.assertEqual(blocks[0]["page"], 7)
        eq = parse_blocks('<a id="E003"></a>\n**Source:** p.7 E003 · Eq. (3.1)\n\n'
                          "$$\nx=1\n$$\n")
        self.assertEqual(eq[0]["page"], 7)
        self.assertIn("Eq. (3.1)", eq[0]["source_tail"])

    def test_heading_line_not_merged_into_previous_block(self) -> None:
        body = ('<a id="S001"></a>\n**Source:** p.1 S001\n\n'
                "**Original:** Abstract text.\n\n**中文：** 摘要文字。\n\n"
                "## 1. 引言（Introduction）\n\n"
                '<a id="S002"></a>\n**Source:** p.1 S002\n\n'
                "**Original:** Body.\n\n**中文：** 正文。\n")
        blocks = parse_blocks(body)
        self.assertEqual(blocks[0]["zh"], ["摘要文字。"])
        self.assertEqual(blocks[0]["original"], ["Abstract text."])

    def test_esc_does_not_double_escape(self) -> None:
        self.assertEqual(esc_outside_math(r"ISBN 978-3-030-11887-7\_13"),
                         r"ISBN 978-3-030-11887-7\_13")
        self.assertEqual(esc_outside_math("a_b"), r"a\_b")

    def test_inline_md_external_link(self) -> None:
        out = inline_md("[doi: 10.1000/xyz_1](https://doi.org/10.1000/xyz_1)")
        self.assertIn(r"\href{https://doi.org/10.1000/xyz\_1}{doi: 10.1000/xyz\_1}", out)

    def test_merge_captions_colon(self) -> None:
        block = (
            '<a id="F001"></a>\n### Fig. 1. 中文图题\n\n'
            "**Source:** p.4 C1-001\n\n![Fig. 1](assets/fig-1.png)\n\n"
            "**Original caption:** Figure 1: Symbolic flow chart.\n\n"
            "**中文图注：** 图 1：符号流程图。\n"
        )
        out = merge_captions(block)
        self.assertIn("### Fig. 1. Symbolic flow chart.（符号流程图）", out)

    def test_merge_small_ranges_respects_target(self) -> None:
        lines = [f"text line {i}" for i in range(1, 121)]
        ranges = [(1, 30), (31, 60), (61, 120)]
        merged = plan_chunks.merge_small_ranges(ranges, 40, lines, 35)
        # 31-60 cannot merge into 1-30 (est 66 > 35); stays split.
        self.assertEqual(merged[0], (1, 30))
        self.assertEqual(merged[-1], (61, 120))

    def test_reconcile_headings_finds_missing(self) -> None:
        lines = ["## 1. Introduction", "text", "3. Conclusions and outlook", "more"]
        inv = [{"num": "1", "level": 2, "line": 1, "en": "Introduction"}]
        missing = plan_chunks.reconcile_headings(lines, inv)
        self.assertEqual(len(missing), 1)
        self.assertIn("Conclusions", missing[0])

    def test_doi_validation_flags_malformed(self) -> None:
        lines = ["[1] A. Author. Title. J. Math 1 (2020). doi: 10.10 93/gji",
                 "[2] B. Author. T. doi:10.1016/j.jcp.2011.02.026."]
        entries, uncertainties, _ = gen_references.parse_entries(lines, 1, 2)
        self.assertEqual(len(entries), 2)
        self.assertTrue(any("suspicious DOI" in u for u in uncertainties))
        self.assertFalse(any("entry 2" in u and "DOI" in u for u in uncertainties))

    def test_report_terms_parsing_and_merge(self) -> None:
        text = ("REPORT: S=5 E=1; new_terms=test function→试验函数, "
                "ideal gas→理想气体; boilerplate_lines_dropped=2; uncertainties=1")
        self.assertEqual(merge_terms.report_terms(text),
                         [("test function", "试验函数"), ("ideal gas", "理想气体")])

    def test_references_section_raggedright(self) -> None:
        tex = md_to_tex("## 参考文献（References）\n\n1. Entry one.\n", {})
        self.assertIn("\\section*{参考文献（References）}", tex)
        self.assertIn("\\raggedright", tex)


class StatusTest(unittest.TestCase):
    def test_status_machine(self) -> None:
        tmp = Path("tmp/_selftest")
        tmp.mkdir(parents=True, exist_ok=True)
        p = tmp / "c01.md"
        p.write_text('<a id="S1-001"></a>\nREPORT: S=1 E=0\n', encoding="utf-8")
        self.assertEqual(effective_status(p)[0], "done")
        p.write_text('<a id="S1-001"></a>\nREPORT: S=1 E=0; next_line=9\n',
                     encoding="utf-8")
        self.assertEqual(effective_status(p)[0], "partial")
        p.write_text('<a id="S1-001"></a>\nREPORT: S=2 E=0\n', encoding="utf-8")
        self.assertEqual(effective_status(p)[0], "failed")
        p.unlink()
        self.assertEqual(effective_status(p)[0], "planned")


if __name__ == "__main__":
    unittest.main(verbosity=2)


