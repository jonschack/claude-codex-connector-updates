import tempfile
import unittest
from pathlib import Path

from mcp_newsletter.classifier import classify_all
from mcp_newsletter.models import ServerRecord, ToolRecord
from mcp_newsletter.state import connect, events_for_date, seeded_providers, upsert_server, upsert_tool


def _writeable(provider, server_id, name):
    s = ServerRecord(provider=provider, server_id=server_id, native_surface="connector",
                     name=name, capabilities=["Read & write"])
    classify_all([s])
    return s


class SeedingTests(unittest.TestCase):
    def test_first_run_of_new_provider_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            s = _writeable("cursor", "slack", "Slack")
            seeded = seeded_providers(conn, "2026-05-30")  # empty DB -> nothing seeded
            upsert_server(conn, "2026-05-30", s, provider_seeded="cursor" in seeded)
            conn.commit()
            self.assertEqual(events_for_date(conn, "2026-05-30"), [])

    def test_same_day_rerun_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            s = _writeable("cursor", "slack", "Slack")
            for _ in range(2):
                seeded = seeded_providers(conn, "2026-05-30")
                upsert_server(conn, "2026-05-30", s, provider_seeded="cursor" in seeded)
            conn.commit()
            self.assertEqual(events_for_date(conn, "2026-05-30"), [])  # idempotent + silent

    def test_new_server_next_day_emits(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            day1 = _writeable("cursor", "slack", "Slack")
            seeded = seeded_providers(conn, "2026-05-30")
            upsert_server(conn, "2026-05-30", day1, provider_seeded="cursor" in seeded)
            conn.commit()
            # day 2: provider now seeded (has a row with first_seen=2026-05-30 < 2026-05-31)
            day2 = _writeable("cursor", "linear", "Linear")
            seeded = seeded_providers(conn, "2026-05-31")
            self.assertIn("cursor", seeded)
            upsert_server(conn, "2026-05-31", day2, provider_seeded="cursor" in seeded)
            conn.commit()
            events = events_for_date(conn, "2026-05-31")
            self.assertEqual([e["event_type"] for e in events], ["new_write_server"])
            self.assertEqual(events[0]["server_id"], "linear")

    def test_first_run_suppresses_both_server_and_tool_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            s = _writeable("cursor", "slack", "Slack")
            tool = ToolRecord(provider="cursor", server_id="slack", native_surface="connector",
                              name="create_message", description="Create a message")
            s.tools = [tool]
            classify_all([s])
            seeded = seeded_providers(conn, "2026-05-30")
            upsert_server(conn, "2026-05-30", s, provider_seeded="cursor" in seeded)
            for t in s.tools:
                upsert_tool(conn, "2026-05-30", t, provider_seeded="cursor" in seeded)
            conn.commit()
            self.assertEqual(events_for_date(conn, "2026-05-30"), [])

    def test_existing_provider_with_prior_rows_is_seeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            old = _writeable("claude", "linear", "Linear")
            upsert_server(conn, "2026-05-01", old, provider_seeded=True)
            conn.commit()
            seeded = seeded_providers(conn, "2026-05-30")
            self.assertIn("claude", seeded)


if __name__ == "__main__":
    unittest.main()
