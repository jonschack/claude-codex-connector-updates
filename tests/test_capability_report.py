import unittest

from mcp_newsletter.capability_report import render_capability_highlights

FEED = [
    {"provider": "gemini", "server": "Bigtable", "tool": "create_instance",
     "summary": "Create a new instance.", "example_prompt": '"Claude, create instance"',
     "evidence_tier": "verified_tools", "write_confidence": "high", "source_urls": ["https://x"]},
    {"provider": "codex", "server": "Twilio", "tool": "send_sms",
     "summary": "Send an SMS.", "example_prompt": '"Claude, send sms"',
     "evidence_tier": "claimed_description", "write_confidence": "medium", "source_urls": []},
]
NOTABLE = [{"event_type": "notable_capability", "provider": "gemini", "name": "Bigtable",
            "score": 0.9, "write_confidence": "high", "tool_count": 13}]
SIGNALS = [{"source": "mcp_blog", "title": "MCP Apps", "url": "https://blog.modelcontextprotocol.io/mcp-apps",
            "published": "2026-01-26", "summary": "Interactive UIs in chat"}]


class CapabilityReportTests(unittest.TestCase):
    def test_renders_all_sections(self):
        md = render_capability_highlights(FEED, NOTABLE, SIGNALS, "2026-06-02")
        self.assertIn("Capability Highlights", md)
        self.assertIn("Bigtable", md)
        self.assertIn("create_instance", md)
        self.assertIn("Claude, create instance", md)   # the "what to ask" payload
        self.assertIn("MCP Apps", md)
        self.assertIn("https://blog.modelcontextprotocol.io/mcp-apps", md)
        self.assertIn("verified", md.lower())           # evidence tier framing

    def test_empty_inputs_are_graceful(self):
        md = render_capability_highlights([], [], [], "2026-06-02")
        self.assertIn("Capability Highlights", md)
        self.assertIn("No tool-level capabilities", md)

    def test_scraped_freetext_cannot_break_markdown(self):
        feed = [{"provider": "p", "server": "Evil] (x)", "tool": "do`it",
                 "summary": "line1\nline2\n  spaced", "example_prompt": '"Claude, do\nit"',
                 "evidence_tier": "claimed_description", "write_confidence": "low", "source_urls": []}]
        signals = [{"source": "s\nrc", "title": "Title with ] and (paren)", "url": "https://x"}]
        md = render_capability_highlights(feed, [], signals, "2026-06-02")
        # no scraped newline survives into a list item
        for line in md.splitlines():
            if line.startswith("- ") or line.startswith("  - "):
                self.assertNotIn("\t", line)
        self.assertNotIn("line1\nline2", md)
        self.assertIn("line1 line2 spaced", md)
        # link title brackets neutralized
        self.assertIn("Title with ) and (paren)", md)

    def test_top_n_truncates_with_overflow_note(self):
        big = [dict(FEED[0], tool=f"t{i}", server=f"S{i}") for i in range(40)]
        md = render_capability_highlights(big, [], [], "2026-06-02", top_n=10)
        self.assertIn("30 more", md)


if __name__ == "__main__":
    unittest.main()
