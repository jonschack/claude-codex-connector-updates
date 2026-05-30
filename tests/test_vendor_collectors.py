import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.providers.openai import collect_openai

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


if __name__ == "__main__":
    unittest.main()
