# tests/test_registry_reporting.py
import unittest

from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_reporting import render_registry_section


class ReportingTests(unittest.TestCase):
    def _recs(self):
        return {
            "a": RegistryServerRecord(identity="a", name="Slack", write_confidence="high",
                                      sources=[{"source": "official"}, {"source": "glama"}]),
            "b": RegistryServerRecord(identity="b", name="ReadOnly", write_confidence="low",
                                      sources=[{"source": "glama"}]),
        }

    def test_section_has_counts_and_double_count_note(self):
        events = [{"event_type": "new_write_server", "identity": "a",
                   "confidence": "high", "summary": "New write-capable server: Slack",
                   "sources": ["official", "glama"]}]
        out = render_registry_section(
            run_date="2026-05-30", records=self._recs(), events=events,
            enabled=["official", "glama"], per_source={"official": 1, "glama": 2},
            new_source_count=0, row_cap=25,
        )
        self.assertIn("## Ecosystem Registries", out)
        self.assertIn("Indexed servers (deduped): 2", out)
        self.assertIn("Write-capable", out)
        self.assertIn("both the vendor", out.lower() if False else out)  # double-count note present
        self.assertIn("new_write_server", out)

    def test_rows_capped(self):
        events = [{"event_type": "new_write_server", "identity": str(i),
                   "confidence": "high", "summary": f"s{i}", "sources": ["official"]}
                  for i in range(40)]
        out = render_registry_section("2026-05-30", self._recs(), events,
                                      ["official"], {"official": 40}, 0, row_cap=25)
        self.assertIn("additional", out)  # overflow pointer present


if __name__ == "__main__":
    unittest.main()
