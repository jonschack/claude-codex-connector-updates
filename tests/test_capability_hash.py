import tempfile
import unittest
from pathlib import Path

from mcp_newsletter.models import ToolRecord
from mcp_newsletter.state import connect, events_for_date, upsert_tool


class CapabilityHashTests(unittest.TestCase):
    """Derived capability fields must NOT drive tool_schema_changed events."""

    def test_capability_fields_do_not_fire_schema_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "s.sqlite")
            tool = ToolRecord(
                provider="gemini", server_id="bt", name="create_instance",
                native_surface="connector", description="Create a new instance.",
                input_schema={"required": ["project_id"]}, write_confidence="high",
            )
            upsert_tool(conn, "2026-06-01", tool, provider_seeded=True)
            conn.commit()
            # Second run: only the derived capability fields differ; schema identical.
            tool.capability_summary = "Spin up a Bigtable instance"
            tool.example_prompt = '"Claude, stand up a 3-node cluster"'
            tool.capability_tier = "verified_tools"
            upsert_tool(conn, "2026-06-02", tool, provider_seeded=True)
            conn.commit()
            events = events_for_date(conn, "2026-06-02")
            conn.close()
        types = [e.get("event_type") for e in events]
        self.assertNotIn("tool_schema_changed", types)


if __name__ == "__main__":
    unittest.main()
