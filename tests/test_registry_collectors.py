# tests/test_registry_collectors.py
import json
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.registries.official import collect_official

FIX = Path(__file__).parent / "fixtures" / "registries"


def _ctx(tmp):
    return CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=False)


class OfficialCollectorTests(unittest.TestCase):
    def test_parses_active_servers_and_skips_deleted(self):
        page = (FIX / "official_page1.json").read_text()
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.official.fetch_text",
                            return_value=(page, {"status": 200, "content_type": "application/json", "error": ""})):
                entries = collect_official(ctx)
        names = {e.official_name for e in entries}
        self.assertIn("io.github.acme/slack", names)
        self.assertNotIn("io.github.acme/gone", names)  # status=deleted skipped
        slack = next(e for e in entries if e.official_name == "io.github.acme/slack")
        self.assertEqual(slack.remote_url, "https://mcp.acme.com/slack")
        self.assertEqual(slack.repo_url, "https://github.com/acme/slack")
        self.assertIn("messaging", slack.tags)


if __name__ == "__main__":
    unittest.main()
