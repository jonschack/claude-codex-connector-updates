import unittest

from mcp_newsletter.grok_research import (
    GrokFinding,
    build_extra_heavy_prompts,
    build_query_matrix,
    extract_engagement,
    finding_key,
    merge_into_state,
    parse_grok_findings,
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


class EngagementTests(unittest.TestCase):
    def test_parses_k_ranges_and_plain(self):
        self.assertEqual(extract_engagement("hit 1k-2.6k+ likes with insane"), 2600)
        self.assertEqual(extract_engagement("2k+ like viral posts"), 2000)
        self.assertEqual(extract_engagement("crypto posts (249+ likes)"), 249)
        self.assertEqual(extract_engagement("1982 likes, 180 reposts"), 1982)

    def test_ignores_non_engagement_numbers(self):
        # "17k+ tickers" must NOT be read as engagement; only the likes count
        self.assertEqual(extract_engagement("17k+ tickers, 1.8k+ likes"), 1800)

    def test_no_number_is_zero(self):
        self.assertEqual(extract_engagement("went viral on X"), 0)


class StateMergeTests(unittest.TestCase):
    def _f(self, name, url, why=""):
        return GrokFinding(name=name, source_url=url, why_viral=why)

    def test_first_seen_then_dedup_then_rising(self):
        state = {}
        f1 = self._f("TradingView MCP", "https://github.com/tradesdontlie/tradingview-mcp", "800+ likes")
        state, new, rising = merge_into_state(state, [f1], run_date="2026-06-01")
        self.assertEqual(len(new), 1)
        self.assertEqual(len(rising), 0)
        self.assertEqual(len(state), 1)

        # same post again, no engagement growth -> not new, not rising
        state, new, rising = merge_into_state(state, [self._f("TradingView MCP", "https://github.com/tradesdontlie/tradingview-mcp", "800+ likes")], run_date="2026-06-02")
        self.assertEqual(len(new), 0)
        self.assertEqual(len(rising), 0)
        self.assertEqual(len(state), 1)

        # same post, engagement grew -> rising, first_seen preserved
        state, new, rising = merge_into_state(state, [self._f("TradingView MCP", "https://github.com/tradesdontlie/tradingview-mcp", "2k+ likes")], run_date="2026-06-03")
        self.assertEqual(len(new), 0)
        self.assertEqual(len(rising), 1)
        rec = next(iter(state.values()))
        self.assertEqual(rec["first_seen"], "2026-06-01")
        self.assertEqual(rec["peak_engagement"], 2000)

    def test_dedup_by_url_ignores_name_variation(self):
        state = {}
        state, new, _ = merge_into_state(state, [self._f("TradingView MCP", "https://github.com/tradesdontlie/tradingview-mcp")], "2026-06-01")
        state, new2, _ = merge_into_state(state, [self._f("tradingview-mcp", "https://github.com/tradesdontlie/tradingview-mcp/")], "2026-06-02")
        self.assertEqual(len(new2), 0)  # same URL (trailing slash normalized) -> dedup


class QueryMatrixTests(unittest.TestCase):
    def test_matrix_applies_floor_window_and_seeds(self):
        queries = build_query_matrix(min_faves=10, since="2026-05-05")
        joined = "\n".join(queries)
        self.assertIn("min_faves:10", joined)
        self.assertIn("since:2026-05-05", joined)
        self.assertTrue(any("model context protocol" in q.lower() for q in queries))
        self.assertTrue(any("from:" in q for q in queries))  # seed-account coverage
        self.assertGreaterEqual(len(queries), 8)             # genuinely a matrix


class ExtraHeavyTests(unittest.TestCase):
    def test_ten_diverse_prompts(self):
        prompts = build_extra_heavy_prompts(since="2026-05-02")
        self.assertEqual(len(prompts), 10)
        self.assertEqual(len(set(prompts)), 10)  # all distinct
        for p in prompts:
            self.assertIn("since 2026-05-02", p)
            self.assertIn("code block", p.lower())
            self.assertIn("name | capability", p)
            self.assertIn("10 likes", p)
        joined = " ".join(prompts).lower()
        for lens_kw in ["launched", "creative", "finance", "developer", "productivity", "official"]:
            self.assertIn(lens_kw, joined)

    def test_count_param(self):
        self.assertEqual(len(build_extra_heavy_prompts(since="x", count=5)), 5)


if __name__ == "__main__":
    unittest.main()
