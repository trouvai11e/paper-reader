#!/usr/bin/env python3
"""Selftest for the paper-reader converter and gates.

Usage: uv run selftest.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_references  # noqa: E402
import plan_chunks  # noqa: E402
from readerlib import (  # noqa: E402
    caption_inventory,
    dispatchable,
    effective_status,
    fidelity_missing,
    inline_md,
    is_references_heading,
    math_mask,
    merge_captions,
    promote_headings,
    renumber,
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


