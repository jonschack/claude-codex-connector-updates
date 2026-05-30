import unittest
from unittest import mock

from mcp_newsletter import registry_discovery
from mcp_newsletter.models import ToolRecord
from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_discovery import run_discovery, select_discovery_candidates


def _rec(identity, remote=True):
    return RegistryServerRecord(
        identity=identity, name=identity,
        remote_url=("https://8.8.8.8/" + identity) if remote else "",
    )


class SelectTests(unittest.TestCase):
    def test_only_records_with_remote_url(self):
        recs = [_rec("a", remote=True), _rec("b", remote=False)]
        sel = select_discovery_candidates(recs, cap=10, last_discovered={},
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual([r.identity for r in sel], ["a"])

    def test_never_discovered_first_then_stable_by_identity(self):
        recs = [_rec("c"), _rec("a"), _rec("b")]
        last = {"a": "2026-05-30", "c": "2026-05-30"}  # b never discovered
        sel = select_discovery_candidates(recs, cap=10, last_discovered=last,
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual(sel[0].identity, "b")  # never-discovered wins

    def test_cap_limits_count(self):
        recs = [_rec(x) for x in "abcde"]
        sel = select_discovery_candidates(recs, cap=2, last_discovered={},
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual(len(sel), 2)

    def test_recently_discovered_within_cadence_skipped(self):
        recs = [_rec("a")]
        sel = select_discovery_candidates(recs, cap=10,
                                          last_discovered={"a": "2026-05-29"},
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual(sel, [])  # discovered 1 day ago, cadence 3 days

    def test_deterministic_across_calls(self):
        recs = [_rec(x) for x in "edcba"]
        a = select_discovery_candidates(recs, cap=3, last_discovered={},
                                        cadence_days=3, run_date="2026-05-30")
        b = select_discovery_candidates(recs, cap=3, last_discovered={},
                                        cadence_days=3, run_date="2026-05-30")
        self.assertEqual([r.identity for r in a], [r.identity for r in b])

    def test_multiple_never_discovered_sorted_by_identity(self):
        recs = [_rec("y"), _rec("x")]
        sel = select_discovery_candidates(recs, cap=10, last_discovered={},
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual([r.identity for r in sel], ["x", "y"])


class RunDiscoveryTests(unittest.TestCase):
    def test_records_dates_and_tool_confidence(self):
        rec = _rec("a")
        tool = ToolRecord(provider="registry", server_id="a", name="create_issue",
                          native_surface="registry", description="Create an issue")
        with mock.patch.object(registry_discovery, "discover_remote_tools",
                               return_value=([tool], {"ok": True, "tool_count": 1})):
            out = run_discovery([rec], run_date="2026-05-30", workers=2)
        self.assertEqual(out, {"a": "2026-05-30"})
        self.assertIn("tools", rec.confidence_by_source)
        self.assertEqual(rec.confidence_by_source["tools"]["date"], "2026-05-30")

    def test_swallows_per_endpoint_exceptions(self):
        good = _rec("good")
        bad = _rec("bad")

        def fake(provider, server_id, native_surface, url, timeout=15):
            if server_id == "bad":
                raise RuntimeError("boom")
            t = ToolRecord(provider="registry", server_id=server_id, name="create_x",
                           native_surface="registry", description="Create")
            return ([t], {"ok": True})

        with mock.patch.object(registry_discovery, "discover_remote_tools", side_effect=fake):
            out = run_discovery([good, bad], run_date="2026-05-30", workers=2)
        self.assertIn("good", out)
        self.assertNotIn("bad", out)  # excepted future is not recorded


if __name__ == "__main__":
    unittest.main()
