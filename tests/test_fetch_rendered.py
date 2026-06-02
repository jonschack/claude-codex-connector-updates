import os
import unittest

from mcp_newsletter.fetch_rendered import fetch_rendered, firecrawl_map


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


class FirecrawlMapTests(unittest.TestCase):
    def test_no_key_returns_empty(self):
        old = os.environ.pop("FIRECRAWL_API_KEY", None)
        try:
            urls, meta = firecrawl_map("https://x.test")
        finally:
            if old is not None:
                os.environ["FIRECRAWL_API_KEY"] = old
        self.assertEqual(urls, [])
        self.assertIn("FIRECRAWL_API_KEY", meta["error"])

    def test_injected_poster_extracts_urls(self):
        urls, meta = firecrawl_map(
            "https://x.test",
            _post=lambda url, limit: {"links": [{"url": "https://x/a"}, {"url": "https://x/b"}]},
        )
        self.assertEqual(urls, ["https://x/a", "https://x/b"])
        self.assertEqual(meta["status"], 200)

    def test_injected_poster_plain_string_links(self):
        urls, _ = firecrawl_map("https://x.test", _post=lambda url, limit: {"links": ["https://x/a"]})
        self.assertEqual(urls, ["https://x/a"])

    def test_error_is_captured(self):
        def boom(url, limit):
            raise RuntimeError("map failed")

        urls, meta = firecrawl_map("https://x.test", _post=boom)
        self.assertEqual(urls, [])
        self.assertIn("map failed", meta["error"])


if __name__ == "__main__":
    unittest.main()
