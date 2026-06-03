# tests/test_registry_classify.py
import unittest
from unittest import mock

from mcp_newsletter import registry_discovery
from mcp_newsletter.classifier import evidence_tier
from mcp_newsletter.models import ToolRecord
from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_classify import classify_registry_record, tags_to_capabilities
from mcp_newsletter.registry_discovery import run_discovery


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

    def test_catalog_evidence_does_not_duplicate_on_reclassify(self):
        # classify is called every run; re-running must not pile up duplicate
        # catalog evidence (idempotent merge under a stable key).
        rec = RegistryServerRecord(identity="x", name="Sender",
                                   description="Send and post messages", tags=[])
        classify_registry_record(rec, run_date="2026-05-30")
        first = list(rec.evidence)
        classify_registry_record(rec, run_date="2026-05-31")
        self.assertEqual(rec.evidence, first)


class AnnotationMergeIntegrationTests(unittest.TestCase):
    """P1-0: discovery appends mcp_annotation evidence, then classify runs in the
    same update — the annotation MUST survive (was clobbered by `rec.evidence =`)."""

    def _probe_then_classify(self, tool, run_date="2026-05-30"):
        rec = RegistryServerRecord(identity="a", name="A",
                                   remote_url="https://8.8.8.8/a",
                                   description="A connector")
        with mock.patch.object(registry_discovery, "discover_remote_tools",
                               return_value=([tool], {"ok": True})):
            run_discovery([rec], run_date=run_date, workers=2)
        # precondition: discovery actually appended annotation evidence
        self.assertTrue(any(e.get("kind") == "mcp_annotation" for e in rec.evidence),
                        "discovery did not append annotation evidence")
        classify_registry_record(rec, run_date=run_date)
        return rec

    def test_annotation_survives_classify_and_yields_headline_tier(self):
        tool = ToolRecord(provider="registry", server_id="a", name="post_status",
                          native_surface="registry", description="Post a status",
                          annotations={"readOnlyHint": False})
        rec = self._probe_then_classify(tool)
        # the annotation evidence is preserved through classify...
        self.assertTrue(any(e.get("kind") == "mcp_annotation" for e in rec.evidence))
        # ...and the live tool_text write verb lifts the record to a headline tier.
        self.assertEqual(evidence_tier(rec.evidence), "verified_tools")

    def test_annotation_only_tool_yields_annotation_tier(self):
        # a tool whose only write signal is the destructive hint (no write verb in
        # name/description) lands at the annotation tier, not claimed.
        tool = ToolRecord(provider="registry", server_id="a", name="thing",
                          native_surface="registry", description="a thing",
                          annotations={"destructiveHint": True})
        rec = self._probe_then_classify(tool)
        self.assertEqual(evidence_tier(rec.evidence), "annotation")


class EvidenceTierTests(unittest.TestCase):
    def test_rank_order(self):
        none = evidence_tier([])
        claimed = evidence_tier([{"kind": "registry_description"}])
        declared = evidence_tier([{"kind": "declared_manifest"}])
        annotation = evidence_tier([{"kind": "mcp_annotation"}])
        verified = evidence_tier([{"kind": "tool_text"}])
        self.assertEqual([none, claimed, declared, annotation, verified],
                         ["none", "claimed_description", "declared_manifest",
                          "annotation", "verified_tools"])

    def test_max_tier_wins(self):
        ev = [{"kind": "registry_description"}, {"kind": "mcp_annotation"},
              {"kind": "tool_text"}]
        self.assertEqual(evidence_tier(ev), "verified_tools")

    def test_unknown_kind_treated_as_claimed(self):
        self.assertEqual(evidence_tier([{"kind": "mystery"}]), "claimed_description")


if __name__ == "__main__":
    unittest.main()
