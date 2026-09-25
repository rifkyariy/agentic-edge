import json
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lg_openai_shim as shim  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "gemma4_template.json")


class TestRender(unittest.TestCase):
    """The prompt little-gemma sees must be the prompt llama-server built, or
    the engine comparison measures the template instead of the engine."""

    @classmethod
    def setUpClass(cls):
        with open(FIXTURE) as f:
            cls.fx = json.load(f)

    def test_thinking_off_matches_llama_server_byte_for_byte(self):
        self.assertEqual(shim.render(self.fx["messages"], False), self.fx["off"])

    def test_thinking_on_matches_llama_server_byte_for_byte(self):
        self.assertEqual(shim.render(self.fx["messages"], True), self.fx["on"])

    def test_the_two_differ_only_by_the_think_token(self):
        self.assertEqual(self.fx["on"].replace("<|think|>\n", "", 1), self.fx["off"])

    def test_thinking_on_without_a_system_message_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            shim.render([{"role": "user", "content": "hi"}], True)

    def test_text_parts_are_joined(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "a"},
                                             {"type": "text", "text": "b"}]}]
        self.assertEqual(shim.render(msgs, False), "<|turn>user\nab<turn|>\n<|turn>model\n")


class TestFrames(unittest.TestCase):
    def test_frames_carry_the_prompt_and_end_with_the_empty_line(self):
        text = "x" * 2500 + "é\n" * 3
        data = shim.frames(text)
        self.assertEqual(data[-1:], b"\n")
        got, i = b"", 0
        while i < len(data) - 1:
            magic, kind, w, h, n = struct.unpack("<BBHHI", data[i:i + 10])
            self.assertEqual((magic, kind, w, h), (1, ord("T"), 0, 0))
            self.assertLessEqual(n, shim.FRAME_MAX)
            got += data[i + 10:i + 10 + n]
            i += 10 + n
        self.assertEqual(got.decode("utf-8"), text)


class TestClean(unittest.TestCase):
    def test_turn_marker_is_removed(self):
        self.assertEqual(shim.clean("The answer is (B).<turn|>", []),
                         ("The answer is (B).", "stop"))

    def test_stop_string_cuts_before_it(self):
        self.assertEqual(shim.clean("The answer is (B).\n\nQuestion:\nNext", ["Question:"]),
                         ("The answer is (B).\n\n", "stop"))

    def test_capped_turn_reports_length(self):
        self.assertEqual(shim.clean("loop loop [SERVE_GEN cap]<turn|>", []),
                         ("loop loop", "length"))

    def test_thinking_markers_stay_inline_as_llama_server_returns_them(self):
        raw = "<|channel>thought\nhmm<channel|>The answer is (C).<turn|>"
        self.assertEqual(shim.clean(raw, [])[0],
                         "<|channel>thought\nhmm<channel|>The answer is (C).")


if __name__ == "__main__":
    unittest.main()
