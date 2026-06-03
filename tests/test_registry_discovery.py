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


def _claimed(identity, source="glama"):
    """Never-probed record with a claimed-write signal (claimed_description tier)."""
    r = RegistryServerRecord(identity=identity, name=identity,
                             remote_url="https://8.8.8.8/" + identity,
                             write_confidence="high",
                             sources=[{"source": source}],
                             evidence=[{"kind": "registry_description",
                                        "value": "send", "confidence": "high"}])
    return r


def _none(identity):
    """Never-probed record with NO write signal (none tier) — exploration target."""
    return RegistryServerRecord(identity=identity, name=identity,
                                remote_url="https://8.8.8.8/" + identity)


class BucketedSelectTests(unittest.TestCase):
    def test_exploration_slice_is_reserved_despite_claimed_competition(self):
        claimed = [_claimed(f"c{i}") for i in range(20)]
        explore = [_none("z_explore_1"), _none("z_explore_2")]
        sel = select_discovery_candidates(claimed + explore, cap=10,
                                          last_discovered={}, cadence_days=3,
                                          run_date="2026-06-01")
        chosen = {r.identity for r in sel}
        self.assertEqual(len(sel), 10)
        # at least one none-tier never-probed server is sampled (leaky-prior check)
        self.assertTrue(chosen & {"z_explore_1", "z_explore_2"})

    def test_reverify_slice_reselects_stale_headline_tool(self):
        stale = RegistryServerRecord(
            identity="stale_verified", name="stale", remote_url="https://8.8.8.8/s",
            evidence=[{"kind": "tool_text", "value": "send", "confidence": "high"}],
            confidence_by_source={"tools": {"confidence": "high", "date": "2026-01-01"}})
        fresh_claims = [_claimed(f"c{i}") for i in range(20)]
        # stale was probed 2026-01-01; run 2026-06-01 is >56 days later
        sel = select_discovery_candidates([stale] + fresh_claims, cap=10,
                                          last_discovered={"stale_verified": "2026-01-01"},
                                          cadence_days=3, run_date="2026-06-01")
        self.assertIn("stale_verified", {r.identity for r in sel})

    def test_fresh_verified_tool_not_reverified(self):
        fresh = RegistryServerRecord(
            identity="fresh_verified", name="fresh", remote_url="https://8.8.8.8/f",
            evidence=[{"kind": "tool_text", "value": "send", "confidence": "high"}],
            confidence_by_source={"tools": {"confidence": "high", "date": "2026-05-30"}})
        sel = select_discovery_candidates([fresh], cap=10,
                                          last_discovered={"fresh_verified": "2026-05-30"},
                                          cadence_days=3, run_date="2026-06-01")
        self.assertEqual(sel, [])  # probed 2 days ago, within cadence — not reselected

    def test_new_since_last_run_is_top_priority(self):
        recs = [_claimed("z_new"), _claimed("a_old")]
        sel = select_discovery_candidates(recs, cap=2, last_discovered={},
                                          cadence_days=3, run_date="2026-06-01",
                                          new_identities={"z_new"})
        self.assertEqual(sel[0].identity, "z_new")  # beats alphabetical a_old

    def test_source_authority_outranks_non_authority(self):
        recs = [_claimed("official_one", source="official"), _claimed("b_glama")]
        sel = select_discovery_candidates(recs, cap=2, last_discovered={},
                                          cadence_days=3, run_date="2026-06-01")
        self.assertEqual(sel[0].identity, "official_one")  # beats alphabetical b_glama

    def test_claimed_write_preferred_over_none_in_priority_fill(self):
        claimed = [_claimed(f"c{i}") for i in range(5)]
        none = [_none(f"n{i}") for i in range(5)]
        # cap=3 -> exploration reserve floors to 0, so this isolates the priority fill
        sel = select_discovery_candidates(claimed + none, cap=3, last_discovered={},
                                          cadence_days=3, run_date="2026-06-01")
        self.assertTrue(all(r.identity.startswith("c") for r in sel))


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

    def test_propagates_mcp_annotation_evidence_to_record(self):
        rec = _rec("a")  # has remote_url; _rec helper already in this file
        from mcp_newsletter.models import ToolRecord
        # destructiveHint=True → classify_tool emits an mcp_annotation evidence item
        tool = ToolRecord(provider="registry", server_id="a", name="delete_thing",
                          native_surface="registry", description="Delete a thing",
                          annotations={"destructiveHint": True})
        with mock.patch.object(registry_discovery, "discover_remote_tools",
                               return_value=([tool], {"ok": True})):
            run_discovery([rec], run_date="2026-05-30", workers=2)
        # tools confidence set AND annotation evidence propagated onto the record:
        self.assertIn("tools", rec.confidence_by_source)
        self.assertTrue(any(e.get("kind") == "mcp_annotation" for e in rec.evidence))

    def test_stores_bounded_top_n_write_tools_only(self):
        rec = _rec("a")
        writes = [ToolRecord(provider="registry", server_id="a", name=f"create_{i}",
                             native_surface="registry", description="Create a thing")
                  for i in range(registry_discovery.TOP_N_WRITE_TOOLS + 5)]
        reads = [ToolRecord(provider="registry", server_id="a", name="list_things",
                            native_surface="registry", description="List things",
                            annotations={"readOnlyHint": True})]
        with mock.patch.object(registry_discovery, "discover_remote_tools",
                               return_value=(writes + reads, {"ok": True})):
            run_discovery([rec], run_date="2026-05-30", workers=2)
        # only write tools are persisted, capped at TOP_N_WRITE_TOOLS
        self.assertEqual(len(rec.tools), registry_discovery.TOP_N_WRITE_TOOLS)
        self.assertTrue(all(t.write_confidence in ("medium", "high") for t in rec.tools))
        self.assertNotIn("list_things", [t.name for t in rec.tools])

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
