"""findings/TABLES.md is generated from the committed data; fail if a run, a
summary or the generator changed without regenerating it."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
FINDINGS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "findings", "runs", "jetson")


@unittest.skipUnless(os.path.isdir(FINDINGS), "findings/runs/jetson not present (a board's checkout)")
class TestResultsTables(unittest.TestCase):
    def test_tables_md_and_images_are_up_to_date(self):
        import results_tables
        text, svgs = results_tables.build()
        with open(results_tables.OUT) as fh:
            self.assertEqual(fh.read(), text, "findings/TABLES.md is stale: run python3 benchmark/results_tables.py")
        for name, (svg, _) in svgs.items():
            with open(os.path.join(results_tables.IMG, name + ".svg")) as fh:
                self.assertEqual(fh.read(), svg, "findings/tables/%s.svg is stale" % name)


class TestReplay(unittest.TestCase):
    """replay_lookup.py is the script the manuscript's Table VII came from;
    check its lookup against a plain scan of the history."""

    def test_lookup_matches_a_brute_force_scan(self):
        import random
        import replay_lookup as rl

        def brute(h, k):
            for n in (3, 2):
                if len(h) > n:
                    starts = [s for s in range(len(h) - n) if h[s:s + n] == h[-n:]]
                    if starts:
                        return h[starts[-1] + n:starts[-1] + n + k]
            return []

        rnd = random.Random(7)
        for _ in range(500):
            h = [rnd.randrange(rnd.randint(2, 6)) for _ in range(rnd.randint(0, 40))]
            for k in (1, 2, 3, 4):
                self.assertEqual(rl.lookup(h, k), brute(h, k))

    def test_a_reply_that_repeats_its_prompt_is_drafted(self):
        import replay_lookup as rl
        plain, spec, acc = rl.replay(list("xyzabcdefg"), list("abcdefgabcdefg"), 3)
        self.assertEqual(len("abcdefgabcdefg"), plain + spec + acc)   # every token emitted once
        self.assertGreater(acc, 0)


if __name__ == "__main__":
    unittest.main()
