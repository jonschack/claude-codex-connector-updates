import unittest

from mcp_newsletter.registries.base import RawRegistryEntry, RegistryServerRecord
from mcp_newsletter.registries.merge import identity


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


if __name__ == "__main__":
    unittest.main()
