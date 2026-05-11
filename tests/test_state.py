import tempfile
import unittest
from pathlib import Path

from mcp_newsletter.classifier import classify_all
from mcp_newsletter.models import ServerRecord, ToolRecord
from mcp_newsletter.state import connect, events_for_date, upsert_server, upsert_tool


class StateTests(unittest.TestCase):
    def test_new_write_tool_and_schema_change_events_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            server = ServerRecord(provider="gemini", server_id="ext-server", native_surface="extension", name="Ext")
            tool = ToolRecord(
                provider="gemini",
                server_id="ext-server",
                native_surface="extension",
                name="create_card",
                description="Create a card",
                input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )
            server.tools = [tool]
            classify_all([server])
            upsert_server(conn, "2026-05-11", server)
            upsert_tool(conn, "2026-05-11", tool)
            upsert_server(conn, "2026-05-11", server)
            upsert_tool(conn, "2026-05-11", tool)
            conn.commit()
            events = events_for_date(conn, "2026-05-11")
            self.assertEqual([event["event_type"] for event in events], ["new_write_server", "new_write_tool"])

            tool.input_schema["properties"]["body"] = {"type": "string"}
            classify_all([server])
            upsert_tool(conn, "2026-05-12", tool)
            conn.commit()
            events = events_for_date(conn, "2026-05-12")
            self.assertEqual([event["event_type"] for event in events], ["tool_schema_changed"])


if __name__ == "__main__":
    unittest.main()
