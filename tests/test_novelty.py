import unittest

from mcp_newsletter.models import ServerRecord, ToolRecord
from mcp_newsletter.novelty import is_notable, notable_events, significance_score


def _server(server_id, write="unknown", tools=0, schema=False):
    tr = [
        ToolRecord(provider="p", server_id=server_id, name=f"t{i}", native_surface="connector",
                   input_schema={"type": "object"} if schema else {})
        for i in range(tools)
    ]
    return ServerRecord(provider="p", server_id=server_id, native_surface="connector",
                        name=server_id, write_confidence=write, tools=tr)


class SignificanceTests(unittest.TestCase):
    def test_new_verified_write_server_scores_high(self):
        s = _server("a", write="high", tools=6, schema=True)
        self.assertGreaterEqual(significance_score(s, seen_before=False), 0.6)

    def test_seen_plain_server_scores_low(self):
        s = _server("b", write="unknown", tools=0)
        self.assertLess(significance_score(s, seen_before=True), 0.3)

    def test_first_seen_raises_score(self):
        s = _server("c", write="medium", tools=2)
        self.assertGreater(
            significance_score(s, seen_before=False),
            significance_score(s, seen_before=True),
        )

    def test_is_notable_threshold(self):
        self.assertTrue(is_notable(0.6, threshold=0.5))
        self.assertFalse(is_notable(0.4, threshold=0.5))


class NotableEventsTests(unittest.TestCase):
    def test_only_new_notable_servers_emitted_sorted(self):
        servers = [
            _server("new-big", write="high", tools=6, schema=True),   # new + notable
            _server("seen-big", write="high", tools=6, schema=True),  # notable but already seen
            _server("new-small", write="unknown", tools=0),           # new but not notable
        ]
        events = notable_events(servers, seen_ids={"p/seen-big"}, threshold=0.5)
        ids = [e["server_id"] for e in events]
        self.assertEqual(ids, ["new-big"])
        self.assertEqual(events[0]["event_type"], "notable_capability")
        self.assertGreaterEqual(events[0]["score"], 0.5)

    def test_flood_collapses_to_aggregate(self):
        servers = [_server(f"s{i}", write="high", tools=6, schema=True) for i in range(30)]
        events = notable_events(servers, seen_ids=set(), threshold=0.5, per_source_cap=25)
        agg = [e for e in events if e["event_type"] == "notable_source"]
        indiv = [e for e in events if e["event_type"] == "notable_capability"]
        self.assertEqual(len(agg), 1)
        self.assertEqual(agg[0]["count"], 30)
        self.assertEqual(len(indiv), 25)  # capped per source


if __name__ == "__main__":
    unittest.main()
