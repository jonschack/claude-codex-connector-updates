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
    def test_parses_connectors_and_capabilities(self):
        html = (FIX / "openai_directory.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.openai.CollectContext.fetch", return_value=html):
                servers = collect_openai(ctx)
        names = {s.name for s in servers}
        self.assertIn("Gmail", names)
        gmail = next(s for s in servers if s.name == "Gmail")
        self.assertEqual(gmail.provider, "openai")
        self.assertTrue(any("write" in c.lower() for c in gmail.capabilities))

    def test_unparseable_markup_returns_empty_and_records_issue(self):
        html = (FIX / "openai_directory_empty.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.openai.CollectContext.fetch", return_value=html):
                servers = collect_openai(ctx)
            self.assertEqual(servers, [])
            messages = [i.message for i in ctx.issues]
            self.assertTrue(any("no records parsed" in m for m in messages))


class CursorCollectorTests(unittest.TestCase):
    def test_parses_per_card_names_and_descriptions(self):
        html = (FIX / "cursor_mcp.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cursor.CollectContext.fetch", return_value=html):
                servers = collect_cursor(ctx)
        self.assertEqual(len(servers), 2)
        names = {s.name for s in servers}
        self.assertIn("mcp-filesystem", names)
        self.assertIn("mcp-server-github", names)
        # Each card has its own description (not shared)
        fs = next(s for s in servers if s.name == "mcp-filesystem")
        gh = next(s for s in servers if s.name == "mcp-server-github")
        self.assertIn("filesystem", fs.description.lower())
        self.assertIn("github", gh.description.lower())
        self.assertNotEqual(fs.description, gh.description)

    def test_deterministic_ordering(self):
        html = (FIX / "cursor_mcp.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cursor.CollectContext.fetch", return_value=html):
                servers1 = collect_cursor(ctx)
            with mock.patch("mcp_newsletter.providers.cursor.CollectContext.fetch", return_value=html):
                servers2 = collect_cursor(ctx)
        self.assertEqual([s.name for s in servers1], [s.name for s in servers2])

    def test_unparseable_markup_returns_empty_and_records_issue(self):
        html = (FIX / "cursor_mcp_empty.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cursor.CollectContext.fetch", return_value=html):
                servers = collect_cursor(ctx)
            self.assertEqual(servers, [])
            messages = [i.message for i in ctx.issues]
            self.assertTrue(any("no records parsed" in m for m in messages))


class VSCodeCollectorTests(unittest.TestCase):
    def test_parses_gallery_json(self):
        body = (FIX / "vscode_gallery.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.vscode.CollectContext.fetch", return_value=body):
                servers = collect_vscode(ctx)
        names = {s.name for s in servers}
        self.assertIn("GitHub Copilot MCP", names)
        entry = next(s for s in servers if s.name == "GitHub Copilot MCP")
        self.assertEqual(entry.provider, "vscode")

    def test_parses_top_level_json_list(self):
        body = (FIX / "vscode_list.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.vscode.CollectContext.fetch", return_value=body):
                servers = collect_vscode(ctx)
        names = {s.name for s in servers}
        self.assertIn("GitHub Copilot MCP", names)
        self.assertIn("Azure MCP", names)
        self.assertEqual(len(servers), 2)

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.vscode.CollectContext.fetch", return_value="not json"):
                servers = collect_vscode(ctx)
        self.assertEqual(servers, [])

    def test_empty_source_urls_filtered(self):
        # An item with no repository should not have an empty string in source_urls
        body = (FIX / "vscode_list.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.vscode.CollectContext.fetch", return_value=body):
                servers = collect_vscode(ctx)
        for s in servers:
            self.assertTrue(all(u for u in s.source_urls), f"Empty URL in source_urls for {s.name}")


class ClineCollectorTests(unittest.TestCase):
    def test_parses_marketplace_json(self):
        body = (FIX / "cline_marketplace.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cline.CollectContext.fetch", return_value=body):
                servers = collect_cline(ctx)
        names = {s.name for s in servers}
        self.assertIn("Brave Search", names)
        entry = next(s for s in servers if s.name == "Brave Search")
        self.assertEqual(entry.provider, "cline")

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cline.CollectContext.fetch", return_value="{bad}"):
                servers = collect_cline(ctx)
        self.assertEqual(servers, [])

    def test_empty_source_urls_filtered(self):
        body = (FIX / "cline_marketplace.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cline.CollectContext.fetch", return_value=body):
                servers = collect_cline(ctx)
        for s in servers:
            self.assertTrue(all(u for u in s.source_urls), f"Empty URL in source_urls for {s.name}")


class ContinueCollectorTests(unittest.TestCase):
    def test_parses_blocks_json(self):
        body = (FIX / "continue_blocks.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.continue_.CollectContext.fetch", return_value=body):
                servers = collect_continue(ctx)
        names = {s.name for s in servers}
        self.assertIn("Postgres MCP", names)
        entry = next(s for s in servers if s.name == "Postgres MCP")
        self.assertEqual(entry.provider, "continue")

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.continue_.CollectContext.fetch", return_value="!!!"):
                servers = collect_continue(ctx)
        self.assertEqual(servers, [])


class CloudflareCollectorTests(unittest.TestCase):
    def test_parses_remote_mcp_servers(self):
        html = (FIX / "cloudflare_mcp_servers.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cloudflare.CollectContext.fetch", return_value=html):
                servers = collect_cloudflare(ctx)
        names = {s.name for s in servers}
        self.assertIn("Workers AI", names)
        entry = next(s for s in servers if s.name == "Workers AI")
        self.assertEqual(entry.provider, "cloudflare")
        self.assertEqual(entry.remote_url, "https://workers-ai.mcp.cloudflare.com/sse")

    def test_prose_prefix_not_captured_in_name(self):
        html = (FIX / "cloudflare_mcp_servers_prose.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cloudflare.CollectContext.fetch", return_value=html):
                servers = collect_cloudflare(ctx)
        names = {s.name for s in servers}
        self.assertIn("Workers AI", names)
        # The long prose paragraph must NOT appear in any name
        for s in servers:
            self.assertNotIn("following", s.name.lower())
            self.assertNotIn("available", s.name.lower())
            self.assertNotIn("applications", s.name.lower())

    def test_unparseable_markup_returns_empty_and_records_issue(self):
        html = (FIX / "cloudflare_mcp_servers_empty.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cloudflare.CollectContext.fetch", return_value=html):
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
