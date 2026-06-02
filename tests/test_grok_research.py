import unittest

from mcp_newsletter.grok_research import (
    GrokFinding,
    parse_grok_findings,
    verify_candidates,
)

# Grok is asked to return delimited rows:
#   name | capability | why_viral | source_url | example_prompt
GROK_ANSWER = """
Here are the viral MCP servers I found:

name | capability | why_viral | url | example_prompt
Blender MCP | Build 3D scenes from text | 22k stars, viral launch demo | https://github.com/ahujasid/blender-mcp | "Claude, build a low-poly dragon scene"
WhatsApp MCP | Read/send your real WhatsApp texts | Show HN + security drama | https://github.com/lharries/whatsapp-mcp | "Claude, reply to my landlord"
MysteryServer | Does something amazing | a thread blew up | | "Claude, do the thing"

Hope that helps!
"""

MARKDOWN_TABLE = """
| name | capability | why_viral | url | example_prompt |
| --- | --- | --- | --- | --- |
| Context7 MCP | Inject up-to-date docs | 50k stars | https://github.com/upstash/context7 | "Claude, use Context7" |
"""


class ParseTests(unittest.TestCase):
    def test_parses_delimited_rows_and_skips_header_and_prose(self):
        rows = parse_grok_findings(GROK_ANSWER, query="viral mcp last 2 weeks")
        names = [r.name for r in rows]
        self.assertEqual(names, ["Blender MCP", "WhatsApp MCP", "MysteryServer"])
        self.assertEqual(rows[0].source_url, "https://github.com/ahujasid/blender-mcp")
        self.assertIn("3D scenes", rows[0].capability)
        self.assertEqual(rows[0].query, "viral mcp last 2 weeks")

    def test_parses_markdown_table_rows(self):
        rows = parse_grok_findings(MARKDOWN_TABLE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "Context7 MCP")
        self.assertEqual(rows[0].source_url, "https://github.com/upstash/context7")

    def test_empty_or_garbage_returns_empty(self):
        self.assertEqual(parse_grok_findings(""), [])
        self.assertEqual(parse_grok_findings("no rows here, just prose."), [])


class VerifyTests(unittest.TestCase):
    def _findings(self):
        return [
            GrokFinding(name="Blender MCP", source_url="https://github.com/ahujasid/blender-mcp"),
            GrokFinding(name="WhatsApp MCP", source_url="https://github.com/lharries/whatsapp-mcp"),
            GrokFinding(name="MysteryServer", source_url=""),  # no source -> rejected
        ]

    def test_awesome_match_verifies_without_network(self):
        findings = self._findings()
        verify_candidates(
            findings,
            source_checker=lambda url: False,            # nothing resolves
            known_names={"blender mcp"},                 # but Blender is in the awesome list
        )
        by = {f.name: f for f in findings}
        self.assertEqual(by["Blender MCP"].verdict, "verified")     # matched known list
        self.assertEqual(by["WhatsApp MCP"].verdict, "claimed")     # has source, didn't resolve
        self.assertEqual(by["MysteryServer"].verdict, "rejected")   # no source at all

    def test_resolving_url_verifies(self):
        findings = self._findings()
        verify_candidates(
            findings,
            source_checker=lambda url: "github.com" in url,  # both github urls resolve
            known_names=set(),
        )
        by = {f.name: f for f in findings}
        self.assertEqual(by["Blender MCP"].verdict, "verified")
        self.assertEqual(by["WhatsApp MCP"].verdict, "verified")
        self.assertEqual(by["MysteryServer"].verdict, "rejected")

    def test_source_checker_failure_is_safe(self):
        findings = [GrokFinding(name="X", source_url="https://x.test")]

        def boom(url):
            raise RuntimeError("network down")

        verify_candidates(findings, source_checker=boom, known_names=set())
        # network failure must not crash; falls back to claimed (has a source)
        self.assertEqual(findings[0].verdict, "claimed")


if __name__ == "__main__":
    unittest.main()
