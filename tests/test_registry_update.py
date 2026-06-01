import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.registries.base import RawRegistryEntry, RegistryCollection
from mcp_newsletter.updater import run_registry_update


def _entry(ident):
    return RawRegistryEntry(
        source="official", source_id=ident, official_name=ident,
        name=ident.split("/")[-1], description="Send and post messages",
        repo_url=f"https://github.com/{ident.split('/')[-1]}/repo",
    )


def collect_one(ctx):
    return RegistryCollection(entries=[_entry("io.x/sender")], source_ok={"official": True})


def collect_two(ctx):
    return RegistryCollection(
        entries=[_entry("io.x/sender"), _entry("io.x/poster")],
        source_ok={"official": True},
    )


class RegistryUpdateTests(unittest.TestCase):
    def test_cold_start_silent_then_new_server_emits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all_registries", collect_one):
                first = run_registry_update(root, run_date="2026-05-30", skip_network=True)
            self.assertEqual(first["event_count"], 0)          # cold-start: silent baseline
            self.assertEqual(first["indexed"], 1)              # but state IS persisted
            state_path = root / "data" / "current" / "registry_state.jsonl"
            self.assertTrue(state_path.exists())
            self.assertEqual(len(state_path.read_text().splitlines()), 1)
            with mock.patch("mcp_newsletter.updater.collect_all_registries", collect_two):
                second = run_registry_update(root, run_date="2026-05-31", skip_network=True)
            self.assertEqual(second["event_count"], 1)         # only the NEW server fires
            evs = json.loads((root / "data" / "current" / "registry_events.json").read_text())
            self.assertEqual(evs[0]["event_type"], "new_write_server")
            self.assertEqual(evs[0]["identity"], "io.x/poster")

    def test_unchanged_server_stays_silent_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all_registries", collect_one):
                run_registry_update(root, run_date="2026-05-30", skip_network=True)
                third = run_registry_update(root, run_date="2026-06-02", skip_network=True)
            self.assertEqual(third["event_count"], 0)          # past baseline + unchanged -> no flood


    def test_discovery_cap_and_workers_from_env(self):
        import os
        captured = {}

        def fake_run_discovery(candidates, run_date, workers=8, timeout=15):
            captured["n"] = len(candidates)
            captured["workers"] = workers
            return {}

        def _entry_with_url(ident):
            return RawRegistryEntry(
                source="official", source_id=ident, official_name=ident,
                name=ident.split("/")[-1], description="A remote server",
                repo_url=f"https://github.com/{ident.split('/')[-1]}/repo",
                remote_url=f"https://mcp.example.com/{ident}",
            )

        def collect_with_urls(ctx):
            return RegistryCollection(
                entries=[
                    _entry_with_url("io.x/alpha"),
                    _entry_with_url("io.x/beta"),
                    _entry_with_url("io.x/gamma"),
                ],
                source_ok={"official": True},
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all_registries", collect_with_urls), \
                 mock.patch("mcp_newsletter.updater.run_discovery", side_effect=fake_run_discovery), \
                 mock.patch.dict(os.environ, {
                     "MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP": "2",
                     "MCP_NEWSLETTER_REGISTRY_DISCOVERY_WORKERS": "4",
                     "MCP_NEWSLETTER_REGISTRY_DISCOVERY_CADENCE_DAYS": "0",
                 }):
                run_registry_update(root, run_date="2026-05-31", skip_network=False)

        self.assertLessEqual(captured["n"], 2)   # cap honored by selection
        self.assertEqual(captured["workers"], 4)  # workers from env


if __name__ == "__main__":
    unittest.main()
