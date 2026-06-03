import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.signals import collect_signals, parse_feed, parse_hn_algolia

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>MCP Blog</title>
  <entry>
    <title>MCP Apps: interactive UIs in chat</title>
    <link href="https://blog.modelcontextprotocol.io/posts/mcp-apps"/>
    <updated>2026-01-26T00:00:00Z</updated>
    <summary>Tools can return live interactive UI rendered in the conversation.</summary>
  </entry>
</feed>
"""

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Anthropic News</title>
  <item>
    <title>Claude in Chrome</title>
    <link>https://www.anthropic.com/news/claude-in-chrome</link>
    <pubDate>Mon, 27 Apr 2026 00:00:00 GMT</pubDate>
    <description>Claude can read, click, and navigate websites with you.</description>
  </item>
</channel></rss>
"""


class ParseFeedTests(unittest.TestCase):
    def test_parses_atom(self):
        recs = parse_feed(ATOM, "mcp_blog")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].title, "MCP Apps: interactive UIs in chat")
        self.assertEqual(recs[0].url, "https://blog.modelcontextprotocol.io/posts/mcp-apps")
        self.assertIn("interactive UI", recs[0].summary)
        self.assertEqual(recs[0].source, "mcp_blog")

    def test_parses_rss(self):
        recs = parse_feed(RSS, "anthropic")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].title, "Claude in Chrome")
        self.assertEqual(recs[0].url, "https://www.anthropic.com/news/claude-in-chrome")

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_feed("not xml", "x"), [])


class HnAlgoliaTests(unittest.TestCase):
    def test_parses_hits_with_url_and_text_fallback(self):
        import json
        payload = {"hits": [
            {"title": "Show HN: my MCP server", "url": "https://github.com/a/b",
             "objectID": "111", "created_at": "2026-06-01T00:00:00Z"},
            {"title": "Ask HN: best MCP setup?", "url": "", "objectID": "222",
             "created_at": "2026-06-02T00:00:00Z", "story_text": "what do you use"},
            {"title": "", "objectID": "333"},  # no title -> skipped
        ]}
        out = parse_hn_algolia(json.dumps(payload))
        self.assertEqual([r.title for r in out],
                         ["Show HN: my MCP server", "Ask HN: best MCP setup?"])
        self.assertEqual(out[0].url, "https://github.com/a/b")
        self.assertEqual(out[1].url, "https://news.ycombinator.com/item?id=222")  # text-post fallback
        self.assertEqual(out[0].source, "hackernews")

    def test_garbage_is_empty(self):
        self.assertEqual(parse_hn_algolia("not json"), [])


class CollectSignalsTests(unittest.TestCase):
    def test_collects_across_feeds(self):
        feeds = {"mcp_blog": "https://blog.modelcontextprotocol.io/atom.xml",
                 "anthropic": "https://www.anthropic.com/rss.xml"}
        bodies = {feeds["mcp_blog"]: ATOM, feeds["anthropic"]: RSS}
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="d", skip_network=False)
            with mock.patch.object(ctx, "fetch", side_effect=lambda p, u, l=None, **k: bodies.get(u)):
                recs = collect_signals(ctx, feeds=feeds)
        titles = {r.title for r in recs}
        self.assertIn("MCP Apps: interactive UIs in chat", titles)
        self.assertIn("Claude in Chrome", titles)

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="d", skip_network=True)
            self.assertEqual(collect_signals(ctx, feeds={"x": "https://x/feed"}), [])


if __name__ == "__main__":
    unittest.main()
