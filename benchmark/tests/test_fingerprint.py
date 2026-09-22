import unittest

from jobqueue import fingerprint

# The Jetson's resolved command line before 2026-09-22. Neither -rea nor
# --reasoning-budget is present, so -rea fell back to 'auto', Gemma's template
# turned thinking on, and the default --reasoning-format auto filed the thoughts
# under reasoning_content where lm-eval never reads them. Every Jetson MMLU-Pro
# run before that date lost its answer this way: median response 993 characters
# against the Pi's 1,880, and 11 of 100 completely empty.
JETSON_BROKEN = (
    "/home/ari/build/llama.cpp/build/bin/llama-server "
    "-m /home/ari/research/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf "
    "-c 8192 --host 127.0.0.1 --port 8080 -ngl 99 --cache-ram 0")

JETSON_FIXED = (
    "/home/ari/build/llama.cpp/build/bin/llama-server "
    "-m /home/ari/research/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf "
    "-c 8192 --host 127.0.0.1 --port 8080 -ngl 99 "
    "-rea off --reasoning-budget -1 --cache-ram 0")

PI_BASELINE = (
    "/home/mitlab/llama.cpp/build/bin/llama-server "
    "-m /home/mitlab/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf "
    "-t 3 -c 8192 --host 127.0.0.1 --port 8080 -rea off --reasoning-budget -1 "
    "--cache-ram 0")


class TestParseFlags(unittest.TestCase):
    def test_reads_the_flags_the_baseline_asserts_on(self):
        f = fingerprint.parse_flags(PI_BASELINE)
        self.assertEqual(f["ctx"], "8192")
        self.assertEqual(f["reasoning"], "off")
        self.assertEqual(f["reasoning_budget"], "-1")
        self.assertEqual(f["cache_ram"], "0")

    def test_absent_flags_read_as_none(self):
        f = fingerprint.parse_flags(JETSON_BROKEN)
        self.assertIsNone(f["reasoning"])
        self.assertIsNone(f["reasoning_budget"])

    def test_long_form_reasoning_is_the_same_flag_as_rea(self):
        # -rea is the short form of --reasoning, the thinking switch. It is NOT
        # --reasoning-format, which is a separate flag. AGENTS §5 had these
        # confused until 2026-09-22.
        f = fingerprint.parse_flags("llama-server --reasoning off")
        self.assertEqual(f["reasoning"], "off")

    def test_reasoning_format_is_not_confused_with_reasoning(self):
        f = fingerprint.parse_flags("llama-server -rea on --reasoning-format none")
        self.assertEqual(f["reasoning"], "on")
        self.assertEqual(f["reasoning_format"], "none")

    def test_reads_model_and_ngl(self):
        f = fingerprint.parse_flags(JETSON_FIXED)
        self.assertTrue(f["model"].endswith("gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"))
        self.assertEqual(f["ngl"], "99")

    def test_empty_command_line_yields_all_none(self):
        f = fingerprint.parse_flags("")
        self.assertIsNone(f["ctx"])


class TestDiff(unittest.TestCase):
    def setUp(self):
        self.baselines = fingerprint.load_baselines()

    def test_the_2026_09_22_jetson_regression_is_caught(self):
        rows = fingerprint.diff(fingerprint.parse_flags(JETSON_BROKEN),
                                self.baselines["mmlupro-baseline"]["flags"])
        self.assertFalse(fingerprint.agrees(rows))
        bad = [r["key"] for r in rows if not r["ok"]]
        self.assertIn("reasoning", bad)

    def test_the_corrected_jetson_command_agrees(self):
        rows = fingerprint.diff(fingerprint.parse_flags(JETSON_FIXED),
                                self.baselines["mmlupro-baseline"]["flags"])
        self.assertTrue(fingerprint.agrees(rows), rows)

    def test_the_pi_baseline_agrees_with_the_same_declaration(self):
        # Both boards must satisfy one declaration or the comparison is void.
        rows = fingerprint.diff(fingerprint.parse_flags(PI_BASELINE),
                                self.baselines["mmlupro-baseline"]["flags"])
        self.assertTrue(fingerprint.agrees(rows), rows)

    def test_a_4096_context_is_caught(self):
        # The deployed default truncates: the longest subset prompt is 2,427
        # tokens and the answer budget is 2,048 (AGENTS §4.4).
        line = PI_BASELINE.replace("-c 8192", "-c 4096")
        rows = fingerprint.diff(fingerprint.parse_flags(line),
                                self.baselines["mmlupro-baseline"]["flags"])
        self.assertIn("ctx", [r["key"] for r in rows if not r["ok"]])

    def test_thinking_on_baseline_requires_reasoning_format_none(self):
        flags = fingerprint.parse_flags(
            "llama-server -c 8192 --cache-ram 0 -rea on --reasoning-budget 320")
        rows = fingerprint.diff(flags, self.baselines["mmlupro-thinking-on"]["flags"])
        self.assertIn("reasoning_format", [r["key"] for r in rows if not r["ok"]])

    def test_diff_rows_carry_both_values_for_display(self):
        rows = fingerprint.diff(fingerprint.parse_flags(JETSON_BROKEN),
                                self.baselines["mmlupro-baseline"]["flags"])
        row = next(r for r in rows if r["key"] == "reasoning")
        self.assertEqual(row["expected"], "off")
        self.assertIsNone(row["actual"])


class TestCapture(unittest.TestCase):
    def test_capture_uses_the_injected_runner(self):
        calls = []

        def fake(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == "ps":
                return PI_BASELINE
            if cmd[0] == "curl":
                return '{"model_path": "/home/mitlab/models/x.gguf"}'
            return "somevalue"

        got = fingerprint.capture(runner=fake)
        self.assertEqual(got["flags"]["reasoning"], "off")
        self.assertEqual(got["model_path"], "/home/mitlab/models/x.gguf")
        self.assertIn(["ps", "-o", "args=", "-C", "llama-server"], calls)

    def test_capture_survives_an_unparseable_props_response(self):
        got = fingerprint.capture(runner=lambda cmd, **kw:
                                  PI_BASELINE if cmd[0] == "ps" else "not json")
        self.assertEqual(got["model_path"], "")


if __name__ == "__main__":
    unittest.main()
