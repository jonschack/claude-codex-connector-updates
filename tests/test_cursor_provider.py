import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.providers import cursor as cursor_mod
from mcp_newsletter.providers.cursor import collect_cursor


class CursorProviderTests(unittest.TestCase):
    def test_filters_mcp_plugins_from_map(self):
        urls = [
            "https://cursor.directory/plugins/mcp-supabase",
            "https://cursor.directory/plugins/bright-data-mcp",
            "https://cursor.directory/plugins/some-rule",
            "https://cursor.directory/rules/other",
            "https://cursor.directory/plugins/mcp-duckdb/",  # trailing slash
            "https://cursor.directory/plugins/mcp-supabase",  # dup
        ]
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="d", skip_network=False)
            with mock.patch.object(cursor_mod, "firecrawl_map", return_value=(urls, {"status": 200})):
                servers = collect_cursor(ctx)
        ids = sorted(s.server_id for s in servers)
        self.assertEqual(ids, ["bright-data-mcp", "mcp-duckdb", "mcp-supabase"])
        self.assertTrue(all(s.provider == "cursor" for s in servers))

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="d", skip_network=True)
            self.assertEqual(collect_cursor(ctx), [])

    def test_no_key_adds_issue_and_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="d", skip_network=False)
            with mock.patch.object(cursor_mod, "firecrawl_map", return_value=([], {"error": "FIRECRAWL_API_KEY not set"})):
                servers = collect_cursor(ctx)
        self.assertEqual(servers, [])
        self.assertTrue(any("FIRECRAWL_API_KEY" in i.message for i in ctx.issues))


if __name__ == "__main__":
    unittest.main()
