import unittest

from mcp_newsletter.fetch_rendered import fetch_rendered


class FetchRenderedTests(unittest.TestCase):
    def test_disabled_by_default(self):
        text, meta = fetch_rendered("https://x.test", backend="none")
        self.assertIsNone(text)
        self.assertIn("disabled", meta["error"])
        self.assertEqual(meta["url"], "https://x.test")

    def test_injected_backend_returns_content(self):
        def fake(url, **kw):
            return "# rendered markdown", {"status": 200}

        text, meta = fetch_rendered("https://x.test", backend="custom", _backend=fake)
        self.assertEqual(text, "# rendered markdown")
        self.assertEqual(meta["status"], 200)
        self.assertEqual(meta["error"], "")

    def test_injected_backend_error_is_captured(self):
        def boom(url, **kw):
            raise RuntimeError("render failed")

        text, meta = fetch_rendered("https://x.test", backend="custom", _backend=boom)
        self.assertIsNone(text)
        self.assertIn("render failed", meta["error"])

    def test_unknown_backend_is_reported(self):
        text, meta = fetch_rendered("https://x.test", backend="does-not-exist")
        self.assertIsNone(text)
        self.assertIn("unknown render backend", meta["error"])


if __name__ == "__main__":
    unittest.main()
