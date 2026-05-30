# tests/test_registry_classify.py
import unittest

from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_classify import classify_registry_record, tags_to_capabilities


class RegistryClassifyTests(unittest.TestCase):
    def test_write_tag_maps_to_write_capability(self):
        caps = tags_to_capabilities(["productivity", "write"])
        self.assertIn("Write", caps)

    def test_action_tag_maps_to_write(self):
        caps = tags_to_capabilities(["automation"])
        self.assertIn("Write", caps)

    def test_read_only_tag_does_not_imply_write(self):
        caps = tags_to_capabilities(["search", "read"])
        self.assertNotIn("Write", caps)

    def test_classify_records_catalog_evidence_source(self):
        rec = RegistryServerRecord(identity="x", name="Sender",
                                   description="Send and post messages", tags=[])
        classify_registry_record(rec, run_date="2026-05-30")
        self.assertIn(rec.write_confidence, {"medium", "high"})
        self.assertIn("catalog", rec.confidence_by_source)
        self.assertEqual(rec.confidence_by_source["catalog"]["date"], "2026-05-30")

    def test_tool_evidence_source_recorded_when_tools_classified(self):
        rec = RegistryServerRecord(identity="x", name="X")
        rec.confidence_by_source = {"tools": {"confidence": "high", "date": "2026-05-29"}}
        classify_registry_record(rec, run_date="2026-05-30")
        # effective confidence takes max across non-stale sources
        self.assertEqual(rec.write_confidence, "high")


if __name__ == "__main__":
    unittest.main()
