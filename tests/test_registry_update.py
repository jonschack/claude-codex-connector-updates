import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.registries.base import RawRegistryEntry, RegistryCollection
from mcp_newsletter.updater import run_registry_update


def fake_collect(ctx):
    return RegistryCollection(
        entries=[
            RawRegistryEntry(source="official", source_id="io.x/sender",
                             official_name="io.x/sender", name="Sender",
                             description="Send and post messages",
                             repo_url="https://github.com/x/sender"),
        ],
        source_ok={"official": True},
    )


class RegistryUpdateTests(unittest.TestCase):
    def test_first_run_seeds_silently_then_emits_next_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all_registries", fake_collect):
                first = run_registry_update(root, run_date="2026-05-30", skip_network=True)
                self.assertEqual(first["event_count"], 0)  # cold-start silent
                self.assertTrue((root / "data" / "current" / "registry_state.jsonl").exists())
                second = run_registry_update(root, run_date="2026-05-31", skip_network=True)
            self.assertGreaterEqual(second["event_count"], 1)  # now past baseline


if __name__ == "__main__":
    unittest.main()
