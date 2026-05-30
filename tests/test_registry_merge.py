import unittest

from mcp_newsletter.registries.base import RawRegistryEntry, RegistryServerRecord
from mcp_newsletter.registries.merge import identity, merge_entries


class ModelTests(unittest.TestCase):
    def test_record_jsonl_roundtrip_is_stable(self):
        rec = RegistryServerRecord(
            identity="io.github.acme/slack",
            name="Slack",
            description="Send messages",
            repo_url="https://github.com/acme/slack",
            remote_url="https://mcp.acme.com/slack",
            sources=[{"source": "official", "source_id": "io.github.acme/slack",
                      "source_url": "https://registry...", "tags": ["chat"], "last_updated": "2026-05-30"}],
            capabilities=["Write"],
            tags=["chat"],
            write_confidence="high",
            confidence_by_source={"catalog": {"confidence": "high", "date": "2026-05-30"}},
        )
        line = rec.to_jsonl()
        back = RegistryServerRecord.from_jsonl(line)
        self.assertEqual(back.to_jsonl(), line)
        self.assertEqual(back.identity, "io.github.acme/slack")

    def test_raw_entry_defaults(self):
        entry = RawRegistryEntry(source="glama", source_id="acme/slack", name="Slack")
        self.assertEqual(entry.tags, [])
        self.assertEqual(entry.repo_url, "")


class IdentityTests(unittest.TestCase):
    def test_official_name_wins(self):
        e = RawRegistryEntry(source="official", source_id="x", name="Slack",
                             official_name="io.github.acme/slack",
                             repo_url="https://github.com/acme/slack")
        self.assertEqual(identity(e), "io.github.acme/slack")

    def test_repo_with_subpath_distinguishes_monorepo_servers(self):
        e1 = RawRegistryEntry(source="glama", source_id="a", name="Fetch",
                              repo_url="https://github.com/modelcontextprotocol/servers",
                              subpath="src/fetch")
        e2 = RawRegistryEntry(source="glama", source_id="b", name="Git",
                              repo_url="https://github.com/modelcontextprotocol/servers",
                              subpath="src/git")
        self.assertNotEqual(identity(e1), identity(e2))
        self.assertTrue(identity(e1).endswith("#src/fetch"))

    def test_repo_without_subpath_uses_repo_root(self):
        e = RawRegistryEntry(source="glama", source_id="a", name="Solo",
                             repo_url="https://github.com/acme/solo")
        self.assertEqual(identity(e), "repo:github.com/acme/solo")

    def test_repo_url_normalized(self):
        e = RawRegistryEntry(source="glama", source_id="a", name="Solo",
                             repo_url="https://GitHub.com/Acme/Solo.git/")
        self.assertEqual(identity(e), "repo:github.com/acme/solo")

    def test_fallback_to_source_slug(self):
        e = RawRegistryEntry(source="mcpso", source_id="weather-thing", name="Weather Thing")
        self.assertEqual(identity(e), "mcpso:weather-thing")


class MergeTests(unittest.TestCase):
    def test_same_server_across_sources_collapses_to_one(self):
        entries = [
            RawRegistryEntry(source="official", source_id="x", name="Slack",
                             official_name="io.github.acme/slack",
                             repo_url="https://github.com/acme/slack", tags=["chat"]),
            RawRegistryEntry(source="glama", source_id="acme/slack", name="Slack MCP",
                             repo_url="https://github.com/acme/slack", subpath="",
                             official_name="io.github.acme/slack", tags=["messaging"]),
        ]
        records = merge_entries(entries, aliases={})
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.identity, "io.github.acme/slack")
        self.assertEqual({s["source"] for s in rec.sources}, {"official", "glama"})
        self.assertIn("chat", rec.tags)
        self.assertIn("messaging", rec.tags)

    def test_monorepo_servers_stay_separate(self):
        entries = [
            RawRegistryEntry(source="glama", source_id="a", name="Fetch",
                             repo_url="https://github.com/modelcontextprotocol/servers",
                             subpath="src/fetch"),
            RawRegistryEntry(source="glama", source_id="b", name="Git",
                             repo_url="https://github.com/modelcontextprotocol/servers",
                             subpath="src/git"),
        ]
        records = merge_entries(entries, aliases={})
        self.assertEqual(len(records), 2)

    def test_alias_remaps_to_prior_canonical_identity(self):
        # a server first known by repo identity; now also carries an official name.
        entries = [
            RawRegistryEntry(source="official", source_id="x", name="Slack",
                             official_name="io.github.acme/slack",
                             repo_url="https://github.com/acme/slack"),
        ]
        aliases = {"repo:github.com/acme/slack": "repo:github.com/acme/slack"}
        records = merge_entries(entries, aliases=aliases)
        # The repo alias already maps to the older canonical id, so reuse it
        self.assertEqual(records[0].identity, "repo:github.com/acme/slack")

    def test_output_sorted_by_identity(self):
        entries = [
            RawRegistryEntry(source="mcpso", source_id="z", name="Zebra"),
            RawRegistryEntry(source="mcpso", source_id="a", name="Apple"),
        ]
        records = merge_entries(entries, aliases={})
        ids = [r.identity for r in records]
        self.assertEqual(ids, sorted(ids))


if __name__ == "__main__":
    unittest.main()
