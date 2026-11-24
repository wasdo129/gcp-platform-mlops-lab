import importlib.util
import io
import unittest
from email.message import Message
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/qwen-smoke.py"
SPEC = importlib.util.spec_from_file_location("qwen_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StreamTests(unittest.TestCase):
    def test_accepts_content_usage_and_done(self):
        response = io.BytesIO(
            b': keepalive\n\ndata: {"choices":[{"delta":{"content":"one"}}]}\n\n'
            b'data: {"choices":[],"usage":{"completion_tokens":1}}\n\ndata: [DONE]\n\n'
        )
        response.headers = Message()
        response.headers["Content-Type"] = "text/event-stream; charset=utf-8"
        events = list(MODULE.stream_events(response))
        self.assertEqual(events[0]["choices"][0]["delta"]["content"], "one")
        self.assertEqual(events[1]["usage"]["completion_tokens"], 1)
        self.assertIsNone(events[2])

    def test_rejects_non_stream_response(self):
        response = io.BytesIO(b'{"choices":[]}')
        response.headers = Message()
        response.headers["Content-Type"] = "application/json"
        with self.assertRaisesRegex(ValueError, "Expected an SSE response"):
            list(MODULE.stream_events(response))
