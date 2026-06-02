import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.providers.grok import collect_grok

CONNECTORS_MD = """
# Connectors

Connectors are maintained by xAI and integrate natively with Grok.

| Connector | What it connects |
| --- | --- |
| Gmail & Google Calendar | Gmail messages and Google Calendar events |
| Google Drive | Google Drive files |
| Salesforce | Salesforce CRM: explore objects, query records, create and update |
| SharePoint | Microsoft SharePoint sites and document libraries |

You can also connect a Custom MCP server via tunneling.
"""


def _ctx(tmp):
    return CollectContext(root=Path(tmp), run_date="d", skip_network=False)


class GrokProviderTests(unittest.TestCase):
    def test_matches_documented_builtins(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.object(ctx, "fetch", side_effect=lambda p, u, l=None, **k: CONNECTORS_MD):
                servers = collect_grok(ctx)
        names = {s.name for s in servers}
        self.assertIn("Gmail", names)
        self.assertIn("Google Drive", names)
        self.assertIn("Salesforce", names)
        self.assertIn("SharePoint", names)
        self.assertTrue(all(s.provider == "grok" for s in servers))
        # OneDrive / Microsoft Teams are not in this fixture -> not matched
        self.assertNotIn("OneDrive", names)

    def test_no_matches_falls_back_to_single_docs_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.object(ctx, "fetch", side_effect=lambda p, u, l=None, **k: "page about something unrelated"):
                servers = collect_grok(ctx)
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].server_id, "grok-connectors-docs")

    def test_empty_fetch_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.object(ctx, "fetch", side_effect=lambda p, u, l=None, **k: None):
                servers = collect_grok(ctx)
        self.assertEqual(servers, [])


if __name__ == "__main__":
    unittest.main()
