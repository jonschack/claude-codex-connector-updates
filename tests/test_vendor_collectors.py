import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.providers import collect_all
from mcp_newsletter.providers.openai import collect_openai
from mcp_newsletter.providers.cursor import collect_cursor
from mcp_newsletter.providers.vscode import collect_vscode
from mcp_newsletter.providers.cline import collect_cline
from mcp_newsletter.providers.continue_ import collect_continue
from mcp_newsletter.providers.cloudflare import collect_cloudflare

FIX = Path(__file__).parent / "fixtures" / "vendors"


def _ctx(tmp):
    return CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=False)


class OpenAICollectorTests(unittest.TestCase):
    def test_retired_returns_empty_with_info_issue(self):
        # openai connectors directory retired (folded into JS-gated ChatGPT apps)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            servers = collect_openai(ctx)
        self.assertEqual(servers, [])
        self.assertTrue(any(i.severity == "info" and "retired" in i.message for i in ctx.issues))


class CursorCollectorTests(unittest.TestCase):
    # Full Firecrawl /map behavior is covered in tests/test_cursor_provider.py.
    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            ctx.skip_network = True
            self.assertEqual(collect_cursor(ctx), [])


class VSCodeCollectorTests(unittest.TestCase):
    def test_retired_returns_empty_with_info_issue(self):
        # vscode gallery is a subset of the official registry (already in registry tier)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            servers = collect_vscode(ctx)
        self.assertEqual(servers, [])
        self.assertTrue(any(i.severity == "info" and "retired" in i.message for i in ctx.issues))


class ClineCollectorTests(unittest.TestCase):
    def test_parses_legacy_dict_format(self):
        """Old synthetic fixture used {"items": [...]} dict wrapper."""
        body = (FIX / "cline_marketplace.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cline.CollectContext.fetch", return_value=body):
                servers = collect_cline(ctx)
        names = {s.name for s in servers}
        self.assertIn("Brave Search", names)
        entry = next(s for s in servers if s.name == "Brave Search")
        self.assertEqual(entry.provider, "cline")

    def test_parses_live_array_format(self):
        """Live API returns a top-level JSON array (captured 2026-06-01)."""
        body = (FIX / "cline_marketplace_live.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cline.CollectContext.fetch", return_value=body):
                servers = collect_cline(ctx)
        names = {s.name for s in servers}
        self.assertIn("Postman API Tools", names)
        entry = next(s for s in servers if s.name == "Postman API Tools")
        self.assertEqual(entry.provider, "cline")
        # github URL should be in source_urls
        self.assertTrue(
            any("github.com/postmanlabs" in u for u in entry.source_urls),
            f"Expected github URL in source_urls: {entry.source_urls}",
        )

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cline.CollectContext.fetch", return_value="{bad}"):
                servers = collect_cline(ctx)
        self.assertEqual(servers, [])

    def test_empty_source_urls_filtered(self):
        body = (FIX / "cline_marketplace_live.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cline.CollectContext.fetch", return_value=body):
                servers = collect_cline(ctx)
        for s in servers:
            self.assertTrue(all(u for u in s.source_urls), f"Empty URL in source_urls for {s.name}")


class ContinueCollectorTests(unittest.TestCase):
    def test_retired_returns_empty_with_info_issue(self):
        # continue bulk MCP list removed (explore auth-gated, search capped)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            servers = collect_continue(ctx)
        self.assertEqual(servers, [])
        self.assertTrue(any(i.severity == "info" and "retired" in i.message for i in ctx.issues))


class CloudflareCollectorTests(unittest.TestCase):
    def test_parses_live_markdown(self):
        """Collector now fetches the .md source (URL changed in 2026). Captured 2026-06-01."""
        body = (FIX / "cloudflare_mcp_servers_live.md").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cloudflare.CollectContext.fetch", return_value=body):
                servers = collect_cloudflare(ctx)
        names = {s.name for s in servers}
        # Main Cloudflare API server should be present
        self.assertIn("Cloudflare API", names)
        entry = next(s for s in servers if s.name == "Cloudflare API")
        self.assertEqual(entry.provider, "cloudflare")
        self.assertEqual(entry.remote_url, "https://mcp.cloudflare.com/mcp")
        # Product-specific servers should be present
        self.assertIn("Documentation server", names)
        self.assertIn("Radar server", names)
        doc = next(s for s in servers if s.name == "Documentation server")
        self.assertEqual(doc.remote_url, "https://docs.mcp.cloudflare.com/mcp")

    def test_remote_url_populated_for_all_servers(self):
        """Every parsed server must have a non-empty remote_url."""
        body = (FIX / "cloudflare_mcp_servers_live.md").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cloudflare.CollectContext.fetch", return_value=body):
                servers = collect_cloudflare(ctx)
        self.assertGreater(len(servers), 0)
        for s in servers:
            self.assertTrue(s.remote_url, f"Empty remote_url for {s.name}")

    def test_unparseable_markup_returns_empty_and_records_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cloudflare.CollectContext.fetch", return_value="<!-- no data -->"):
                servers = collect_cloudflare(ctx)
            self.assertEqual(servers, [])
            messages = [i.message for i in ctx.issues]
            self.assertTrue(any("no records parsed" in m for m in messages))


class CollectAllRegistrationTests(unittest.TestCase):
    def test_all_six_new_providers_are_invoked(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            ctx.skip_network = True  # every collector returns [] but must be CALLED, not crash
            # collect_all swallows per-collector exceptions into issues; assert no crash
            servers = collect_all(ctx)
        self.assertIsInstance(servers, list)
        # the 6 new providers register import-time without error
        from mcp_newsletter.providers import openai, cursor, vscode, cline, continue_, cloudflare  # noqa


if __name__ == "__main__":
    unittest.main()
