#!/usr/bin/env python3
"""Selftest for the paper-reader converter and gates.

Usage: uv run selftest.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plan_chunks  # noqa: E402
from readerlib import (  # noqa: E402
    caption_inventory,
    effective_status,
    fidelity_missing,
    inline_md,
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


