import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
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


class CursorCollectorTests(unittest.TestCase):
    def test_parses_github_repos(self):
        html = (FIX / "cursor_mcp.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.cursor.CollectContext.fetch", return_value=html):
                servers = collect_cursor(ctx)
        self.assertTrue(len(servers) >= 1)
        names = {s.name for s in servers}
        self.assertIn("mcp-filesystem", names)
        entry = next(s for s in servers if s.name == "mcp-filesystem")
        self.assertEqual(entry.provider, "cursor")


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

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.vscode.CollectContext.fetch", return_value="not json"):
                servers = collect_vscode(ctx)
        self.assertEqual(servers, [])


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


if __name__ == "__main__":
    unittest.main()
