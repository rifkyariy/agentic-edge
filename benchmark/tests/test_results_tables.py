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
    def test_tables_md_is_up_to_date(self):
        import results_tables
        with open(results_tables.OUT) as fh:
            committed = fh.read()
        self.assertEqual(committed, results_tables.build(),
                         "findings/TABLES.md is stale: run python3 benchmark/results_tables.py")


class TestReplay(unittest.TestCase):
    def test_indexed_lookup_matches_a_brute_force_scan(self):
        import random
        import replay_lookup as rl

        def brute(prompt, reply, width):
            ctx, i, passes, matched = list(prompt), 0, 0, 0
            while i < len(reply):
                draft = []
                for n in (3, 2):
                    if len(ctx) >= n:
                        for e in range(len(ctx) - 1, n - 1, -1):
                            if ctx[e - n:e] == ctx[-n:]:
                                draft = ctx[e:e + width - 1]
                                break
                        if draft:
                            break
                k = 0
                while k < len(draft) and i + k < len(reply) and draft[k] == reply[i + k]:
                    k += 1
                emit = min(k + 1, len(reply) - i)
                ctx += reply[i:i + emit]
                passes, matched, i = passes + 1, matched + bool(draft), i + emit
            return passes, matched

        rnd = random.Random(7)
        for _ in range(200):
            v = rnd.randint(2, 6)
            p = [rnd.randrange(v) for _ in range(rnd.randint(0, 30))]
            r = [rnd.randrange(v) for _ in range(rnd.randint(1, 40))]
            for w in (2, 3, 4, 5):
                self.assertEqual(rl.replay_one(p, r, w), brute(p, r, w))

    def test_a_reply_that_repeats_its_prompt_is_drafted(self):
        import replay_lookup as rl
        passes, matched = rl.replay_one(list("xyzabcdefg"), list("abcdefgabcdefg"), 3)
        self.assertEqual((passes, matched), (6, 4))   # 14 tokens in 6 passes


if __name__ == "__main__":
    unittest.main()
