"""The manuscript's tables, rebuilt from findings/ and checked number by number.

Fails when a committed run no longer reproduces the paper — a run replaced,
a metric changed, a table edited without the data behind it.
"""
import contextlib
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import paper_tables  # noqa: E402

FINDINGS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "findings", "runs", "jetson")


@unittest.skipUnless(os.path.isdir(FINDINGS), "findings/runs/jetson not present (a board's checkout)")
class TestPaperTables(unittest.TestCase):
    def test_every_table_matches_the_manuscript(self):
        paper_tables.FAILS.clear()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            for build in paper_tables.TABLES.values():
                build()
        self.assertEqual(paper_tables.FAILS, [], out.getvalue())

    def test_mcnemar_is_exact_and_two_sided(self):
        a = {i: (None, i < 14) for i in range(27)}
        b = {i: (None, i >= 14) for i in range(27)}
        p, x, y = paper_tables.mcnemar(a, b)
        self.assertEqual((x, y), (14, 13))
        self.assertAlmostEqual(p, 1.0)
        p, _, _ = paper_tables.mcnemar({0: (None, True)}, {0: (None, True)})
        self.assertEqual(p, 1.0)


if __name__ == "__main__":
    unittest.main()
