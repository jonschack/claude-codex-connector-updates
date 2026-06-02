import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.providers.claude import collect_claude


DIRECTORY = (
    '<html><body><nav>Try Claude Contact sales</nav>'
    '<a href="https://claude.com/connectors/acme">Acme</a></body></html>'
)

DETAIL = """
<html><head><title>Acme | Claude</title></head><body>
<nav>Meet Claude Products Claude Code Pricing Try Claude Contact sales</nav>
<main><h1>Acme</h1><p>Acme connects Claude to your warehouse to query and update inventory.</p></main>
<footer>Try Claude Contact sales Anthropic news</footer>
</body></html>
"""


class ClaudeProviderTests(unittest.TestCase):
    def test_description_is_clean_main_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-06-01", skip_network=False)

            def fake_fetch(provider, url, label=None, extra_headers=None):
                if url.rstrip("/") == "https://claude.com/connectors":
                    return DIRECTORY
                return DETAIL

            with mock.patch.object(ctx, "fetch", side_effect=fake_fetch):
                servers = collect_claude(ctx)

            self.assertEqual(len(servers), 1)
            desc = servers[0].description
            self.assertIn("warehouse to query and update inventory", desc)
            self.assertNotIn("Contact sales", desc)
            self.assertNotIn("Anthropic news", desc)


if __name__ == "__main__":
    unittest.main()
