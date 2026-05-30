import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.models import ServerRecord, ToolRecord
from mcp_newsletter.updater import run_update


def fake_collect_all(ctx):
    return [
        ServerRecord(
            provider="codex",
            server_id="fake-plugin",
            native_surface="plugin",
            name="Fake Plugin",
            capabilities=["Write"],
            tools=[
                ToolRecord(
                    provider="codex",
                    server_id="fake-plugin",
                    native_surface="plugin",
                    name="send_message",
                    description="Send a message",
                )
            ],
        )
    ]


class UpdateTests(unittest.TestCase):
    def test_update_is_idempotent_for_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all", fake_collect_all):
                first = run_update(root, run_date="2026-05-11", skip_network=True)
                second = run_update(root, run_date="2026-05-11", skip_network=True)
            self.assertEqual(first["status"]["event_count"], 1)
            self.assertEqual(second["status"]["event_count"], 1)
            self.assertTrue((root / "reports" / "2026-05-11.md").exists())
            self.assertTrue((root / "data" / "current" / "servers.json").exists())


if __name__ == "__main__":
    unittest.main()

