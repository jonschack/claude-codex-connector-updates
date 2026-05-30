import unittest

from mcp_newsletter.registries.base import RawRegistryEntry, RegistryServerRecord


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


if __name__ == "__main__":
    unittest.main()
