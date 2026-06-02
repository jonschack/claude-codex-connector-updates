import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.models import ServerRecord
from mcp_newsletter.updater import run_update


def _one_claude(ctx):
    return [ServerRecord(provider="claude", server_id="x", native_surface="connector", name="X")]


def _many_claude(ctx):
    return [
        ServerRecord(provider="claude", server_id=f"s{i}", native_surface="connector", name=f"S{i}")
        for i in range(30)
    ]


class UpdateHealthTests(unittest.TestCase):
    def test_status_has_health_block_and_flags_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all", _one_claude):
                run_update(root, run_date="2026-06-01", skip_network=True)
            status = json.loads((root / "data/current/status.json").read_text())
            self.assertIn("health", status)
            self.assertTrue(status["health"]["degraded"])  # 1 claude < floor 20
            self.assertIsNotNone(status["health"]["alert"])

    def test_empty_source_escalated_to_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all", _one_claude):
                run_update(root, run_date="2026-06-01", skip_network=True)
            status = json.loads((root / "data/current/status.json").read_text())
            # at least one source (e.g. gemini/codex) collected 0 -> error-severity issue
            sev = [i for i in status["issues"] if i.get("severity") == "error" and i.get("source") == "health"]
            self.assertTrue(sev, "expected an error-severity health issue for an empty source")


if __name__ == "__main__":
    unittest.main()
