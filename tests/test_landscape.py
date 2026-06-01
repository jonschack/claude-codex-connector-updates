"""
Tests for mcp_newsletter/landscape.py — Loop 1 analysis core.

All tests are deterministic: no network, no datetime.now(), no random.
"""

import unittest

from mcp_newsletter.landscape import (
    DEFAULT_TAXONOMY,
    assign_themes,
    coverage,
    estimate_residual_dups,
    evidence_tier,
    rank_servers,
    summarize,
    wilson_interval,
)


# ---------------------------------------------------------------------------
# Helpers for building minimal records
# ---------------------------------------------------------------------------

def _rec(
    identity="srv:test",
    name="Test Server",
    description="",
    repo_url="",
    sources=None,
    write_confidence="unknown",
    evidence=None,
    confidence_by_source=None,
    tags=None,
) -> dict:
    return {
        "identity": identity,
        "name": name,
        "description": description,
        "repo_url": repo_url,
        "remote_url": "",
        "sources": sources or [],
        "capabilities": [],
        "tags": tags or [],
        "write_confidence": write_confidence,
        "evidence": evidence or [],
        "confidence_by_source": confidence_by_source or {},
    }


# ---------------------------------------------------------------------------
# I1 — evidence_tier
# ---------------------------------------------------------------------------

class TestEvidenceTier(unittest.TestCase):

    def test_verified_tools_when_tools_confidence_is_medium(self):
        rec = _rec(
            confidence_by_source={"tools": {"confidence": "medium", "date": "2026-05-01"}},
            write_confidence="medium",
        )
        self.assertEqual(evidence_tier(rec), "verified_tools")

    def test_verified_tools_when_tools_confidence_is_high(self):
        rec = _rec(
            confidence_by_source={"tools": {"confidence": "high", "date": "2026-05-01"}},
            write_confidence="high",
        )
        self.assertEqual(evidence_tier(rec), "verified_tools")

    def test_annotation_tier_from_mcp_annotation_evidence_medium(self):
        rec = _rec(
            evidence=[{"kind": "mcp_annotation", "value": "destructiveHint=true", "confidence": "high"}],
            write_confidence="high",
            confidence_by_source={},
        )
        self.assertEqual(evidence_tier(rec), "annotation")

    def test_annotation_tier_from_mcp_annotation_evidence_high(self):
        rec = _rec(
            evidence=[{"kind": "mcp_annotation", "value": "readOnlyHint=false", "confidence": "medium"}],
            write_confidence="medium",
            confidence_by_source={},
        )
        self.assertEqual(evidence_tier(rec), "annotation")

    def test_annotation_tier_not_fired_when_confidence_is_low(self):
        """Low-confidence mcp_annotation should not trigger annotation tier."""
        rec = _rec(
            evidence=[{"kind": "mcp_annotation", "value": "readOnlyHint=true", "confidence": "low"}],
            confidence_by_source={},
            write_confidence="low",
        )
        # No catalog either → should be none
        self.assertEqual(evidence_tier(rec), "none")

    def test_claimed_description_when_only_catalog_reportable(self):
        rec = _rec(
            confidence_by_source={"catalog": {"confidence": "high", "date": "2026-05-01"}},
            write_confidence="high",
        )
        self.assertEqual(evidence_tier(rec), "claimed_description")

    def test_claimed_description_catalog_medium(self):
        rec = _rec(
            confidence_by_source={"catalog": {"confidence": "medium", "date": "2026-05-01"}},
            write_confidence="medium",
        )
        self.assertEqual(evidence_tier(rec), "claimed_description")

    def test_none_when_write_confidence_not_reportable(self):
        rec = _rec(write_confidence="low", confidence_by_source={})
        self.assertEqual(evidence_tier(rec), "none")

    def test_none_when_write_confidence_unknown(self):
        rec = _rec(write_confidence="unknown", confidence_by_source={})
        self.assertEqual(evidence_tier(rec), "none")

    def test_priority_tools_beats_annotation(self):
        """When both tools (reportable) and annotation exist, verified_tools wins."""
        rec = _rec(
            confidence_by_source={"tools": {"confidence": "medium", "date": "2026-05-01"}},
            evidence=[{"kind": "mcp_annotation", "value": "destructiveHint=true", "confidence": "high"}],
            write_confidence="high",
        )
        self.assertEqual(evidence_tier(rec), "verified_tools")

    def test_priority_annotation_beats_catalog(self):
        """annotation beats claimed_description."""
        rec = _rec(
            confidence_by_source={"catalog": {"confidence": "high", "date": "2026-05-01"}},
            evidence=[{"kind": "mcp_annotation", "value": "destructiveHint=true", "confidence": "high"}],
            write_confidence="high",
        )
        self.assertEqual(evidence_tier(rec), "annotation")

    def test_priority_all_three_present_tools_wins(self):
        rec = _rec(
            confidence_by_source={
                "tools": {"confidence": "high", "date": "2026-05-01"},
                "catalog": {"confidence": "high", "date": "2026-05-01"},
            },
            evidence=[{"kind": "mcp_annotation", "value": "destructiveHint=true", "confidence": "high"}],
            write_confidence="high",
        )
        self.assertEqual(evidence_tier(rec), "verified_tools")

    def test_non_mcp_annotation_evidence_kind_does_not_trigger_annotation_tier(self):
        rec = _rec(
            evidence=[{"kind": "tool_text", "value": "create", "confidence": "medium"}],
            write_confidence="medium",
            confidence_by_source={},
        )
        # tool_text without catalog or tools entry → none
        self.assertEqual(evidence_tier(rec), "none")

    def test_tools_low_confidence_does_not_trigger_verified_tools(self):
        """Tools entry present but confidence is low → not verified_tools."""
        rec = _rec(
            confidence_by_source={"tools": {"confidence": "low", "date": "2026-05-01"}},
            write_confidence="low",
        )
        self.assertEqual(evidence_tier(rec), "none")


# ---------------------------------------------------------------------------
# I2 — coverage
# ---------------------------------------------------------------------------

class TestCoverage(unittest.TestCase):

    def _make_summary(self, enabled, source_ok, per_source):
        return {
            "enabled_sources": enabled,
            "source_ok": source_ok,
            "per_source": per_source,
            "per_source_raw": {},
            "issues": [],
        }

    def test_two_sources_one_failed(self):
        summary = self._make_summary(
            enabled=["glama", "smithery"],
            source_ok={"glama": True, "smithery": False},
            per_source={"glama": 500, "smithery": 0},
        )
        known = {"glama": 1000, "smithery": 2000}
        result = coverage(summary, known)

        self.assertEqual(result["sources_attempted"], ["glama", "smithery"])
        self.assertEqual(result["sources_succeeded"], ["glama"])
        self.assertEqual(result["sources_failed"], ["smithery"])

        glama = result["per_source"]["glama"]
        self.assertEqual(glama["pulled"], 500)
        self.assertEqual(glama["known_estimate"], 1000)
        self.assertAlmostEqual(glama["coverage_pct"], 50.0)

        smithery = result["per_source"]["smithery"]
        self.assertEqual(smithery["pulled"], 0)
        self.assertEqual(smithery["known_estimate"], 2000)
        # smithery failed but coverage_pct is computed from the count
        self.assertAlmostEqual(smithery["coverage_pct"], 0.0)

    def test_failed_source_generates_note(self):
        summary = self._make_summary(
            enabled=["glama", "smithery"],
            source_ok={"glama": True, "smithery": False},
            per_source={"glama": 100, "smithery": 0},
        )
        result = coverage(summary, {})
        notes = result["notes"]
        self.assertTrue(any("smithery" in n for n in notes))
        # glama succeeded — no note for it
        self.assertFalse(any("glama" in n for n in notes))

    def test_overall_coverage_pct_computed_from_succeeded_only(self):
        summary = self._make_summary(
            enabled=["a", "b"],
            source_ok={"a": True, "b": False},
            per_source={"a": 200, "b": 0},
        )
        known = {"a": 400, "b": 1000}
        result = coverage(summary, known)
        # only 'a' succeeded: 200/400 = 50%
        self.assertAlmostEqual(result["overall_coverage_pct"], 50.0)

    def test_overall_coverage_none_when_no_known_estimate_for_succeeded(self):
        summary = self._make_summary(
            enabled=["a"],
            source_ok={"a": True},
            per_source={"a": 100},
        )
        result = coverage(summary, {})
        self.assertIsNone(result["overall_coverage_pct"])

    def test_coverage_capped_at_100(self):
        """Pulled exceeding known estimate → capped at 100.0."""
        summary = self._make_summary(
            enabled=["a"],
            source_ok={"a": True},
            per_source={"a": 150},
        )
        result = coverage(summary, {"a": 100})
        self.assertEqual(result["per_source"]["a"]["coverage_pct"], 100.0)
        self.assertEqual(result["overall_coverage_pct"], 100.0)

    def test_per_source_none_when_known_estimate_missing(self):
        summary = self._make_summary(
            enabled=["a"],
            source_ok={"a": True},
            per_source={"a": 50},
        )
        result = coverage(summary, {})
        self.assertIsNone(result["per_source"]["a"]["coverage_pct"])
        self.assertIsNone(result["per_source"]["a"]["known_estimate"])

    def test_no_notes_when_all_succeed(self):
        summary = self._make_summary(
            enabled=["a", "b"],
            source_ok={"a": True, "b": True},
            per_source={"a": 10, "b": 20},
        )
        result = coverage(summary, {"a": 100, "b": 200})
        self.assertEqual(result["notes"], [])


# ---------------------------------------------------------------------------
# I4 — estimate_residual_dups
# ---------------------------------------------------------------------------

class TestEstimateResidualDups(unittest.TestCase):

    def test_same_repo_url_different_identity(self):
        records = [
            _rec(identity="srv:a", repo_url="https://github.com/foo/bar"),
            _rec(identity="srv:b", repo_url="http://github.com/foo/bar.git"),
        ]
        result = estimate_residual_dups(records)
        self.assertEqual(result["unique_identities"], 2)
        self.assertEqual(result["suspected_dup_clusters"], 1)
        self.assertEqual(result["suspected_extra_records"], 1)
        self.assertEqual(len(result["examples"]), 1)
        cluster = result["examples"][0]
        self.assertIn("srv:a", cluster)
        self.assertIn("srv:b", cluster)

    def test_mixed_case_names_collapse(self):
        records = [
            _rec(identity="srv:x", name="My-MCP-Server"),
            _rec(identity="srv:y", name="myMCPServer"),
        ]
        result = estimate_residual_dups(records)
        self.assertEqual(result["suspected_dup_clusters"], 1)
        self.assertEqual(result["suspected_extra_records"], 1)

    def test_no_dups_when_all_distinct(self):
        records = [
            _rec(identity="srv:1", name="Alpha", repo_url="https://github.com/a/alpha"),
            _rec(identity="srv:2", name="Beta", repo_url="https://github.com/b/beta"),
        ]
        result = estimate_residual_dups(records)
        self.assertEqual(result["suspected_dup_clusters"], 0)
        self.assertEqual(result["suspected_extra_records"], 0)
        self.assertEqual(result["examples"], [])

    def test_three_records_same_repo(self):
        records = [
            _rec(identity="srv:1", repo_url="https://github.com/x/y"),
            _rec(identity="srv:2", repo_url="https://github.com/x/y.git"),
            _rec(identity="srv:3", repo_url="http://github.com/x/y/"),
        ]
        result = estimate_residual_dups(records)
        self.assertEqual(result["suspected_dup_clusters"], 1)
        self.assertEqual(result["suspected_extra_records"], 2)

    def test_examples_capped_at_5(self):
        """Up to 5 example clusters returned."""
        records = []
        for i in range(12):
            base = f"https://github.com/owner/repo{i}"
            records.append(_rec(identity=f"srv:a{i}", repo_url=base))
            records.append(_rec(identity=f"srv:b{i}", repo_url=base + ".git"))
        result = estimate_residual_dups(records)
        self.assertLessEqual(len(result["examples"]), 5)

    def test_empty_records(self):
        result = estimate_residual_dups([])
        self.assertEqual(result["unique_identities"], 0)
        self.assertEqual(result["suspected_dup_clusters"], 0)
        self.assertEqual(result["suspected_extra_records"], 0)
        self.assertEqual(result["examples"], [])

    def test_single_record_no_dups(self):
        records = [_rec(identity="srv:only")]
        result = estimate_residual_dups(records)
        self.assertEqual(result["suspected_dup_clusters"], 0)

    def test_repo_url_scheme_and_git_stripped(self):
        """Ensure https://x/y and http://x/y.git collapse together."""
        records = [
            _rec(identity="id1", repo_url="HTTPS://GitHub.Com/Org/Repo.git"),
            _rec(identity="id2", repo_url="https://github.com/org/repo"),
        ]
        result = estimate_residual_dups(records)
        self.assertEqual(result["suspected_dup_clusters"], 1)

    def test_same_identity_not_counted_as_dup(self):
        """A record whose identity appears once should not form a cluster."""
        records = [
            _rec(identity="srv:solo", name="SoloServer"),
        ]
        result = estimate_residual_dups(records)
        self.assertEqual(result["suspected_dup_clusters"], 0)


# ---------------------------------------------------------------------------
# I7 — assign_themes
# ---------------------------------------------------------------------------

class TestAssignThemes(unittest.TestCase):

    def test_payments_primary_when_matches_payments_and_comms(self):
        """payments/finance/crypto has higher priority than comms/social."""
        rec = _rec(
            name="Stripe Email Sender",
            description="Send invoices and email notifications",
        )
        result = assign_themes(rec)
        self.assertEqual(result["primary"], "payments/finance/crypto")
        self.assertIn("comms/social", result["all"])
        self.assertIn("payments/finance/crypto", result["all"])

    def test_no_match_returns_other(self):
        # Use text with zero keyword overlap with any taxonomy entry
        rec = _rec(name="Unnamed", description="a novel auxiliary MCP server with no recognized category")
        result = assign_themes(rec)
        self.assertEqual(result["primary"], "other")
        self.assertEqual(result["all"], [])

    def test_single_theme_match(self):
        rec = _rec(name="GitHub MCP", description="Manage pull requests and code review")
        result = assign_themes(rec)
        self.assertIn("devtools/git", result["all"])
        self.assertEqual(result["primary"], "devtools/git")

    def test_tags_are_searched(self):
        rec = _rec(name="Mystery", description="", tags=["bitcoin", "wallet"])
        result = assign_themes(rec)
        self.assertEqual(result["primary"], "payments/finance/crypto")

    def test_case_insensitive_matching(self):
        rec = _rec(description="PAYMENT gateway INTEGRATION")
        result = assign_themes(rec)
        self.assertIn("payments/finance/crypto", result["all"])

    def test_multiple_themes_in_all(self):
        rec = _rec(
            name="DevOps Tool",
            description="deploy to kubernetes and send slack notifications",
        )
        result = assign_themes(rec)
        self.assertIn("deploy/cloud/infra", result["all"])
        self.assertIn("comms/social", result["all"])

    def test_priority_deploy_beats_comms(self):
        """deploy/cloud/infra (rank 2) beats comms/social (rank 7)."""
        rec = _rec(description="deploy services and send slack alerts")
        result = assign_themes(rec)
        self.assertEqual(result["primary"], "deploy/cloud/infra")

    def test_custom_taxonomy_respected(self):
        custom_taxonomy = [
            ("widgets", ["widget", "gadget"]),
            ("gizmos", ["gizmo"]),
        ]
        rec = _rec(description="a gizmo and a widget")
        result = assign_themes(rec, taxonomy=custom_taxonomy)
        # widgets comes first in the custom taxonomy
        self.assertEqual(result["primary"], "widgets")
        self.assertIn("gizmos", result["all"])


# ---------------------------------------------------------------------------
# I8 — rank_servers
# ---------------------------------------------------------------------------

class TestRankServers(unittest.TestCase):

    def _verified_rec(self, identity, write_confidence="high", sources=None):
        return _rec(
            identity=identity,
            write_confidence=write_confidence,
            sources=sources or [{"source": "glama"}],
            confidence_by_source={"tools": {"confidence": write_confidence, "date": "2026-05-01"}},
        )

    def _claimed_rec(self, identity, write_confidence="medium", sources=None):
        return _rec(
            identity=identity,
            write_confidence=write_confidence,
            sources=sources or [{"source": "glama"}],
            confidence_by_source={"catalog": {"confidence": write_confidence, "date": "2026-05-01"}},
        )

    def test_verified_tools_beats_claimed_description(self):
        verified = self._verified_rec("srv:v")
        claimed = self._claimed_rec("srv:c")
        ranked = rank_servers([claimed, verified])
        self.assertEqual(ranked[0]["identity"], "srv:v")
        self.assertEqual(ranked[1]["identity"], "srv:c")

    def test_higher_write_confidence_ranked_first_among_same_tier(self):
        high = self._claimed_rec("srv:high", write_confidence="high")
        med = self._claimed_rec("srv:med", write_confidence="medium")
        ranked = rank_servers([med, high])
        self.assertEqual(ranked[0]["identity"], "srv:high")

    def test_source_count_breaks_tie(self):
        a = self._claimed_rec("srv:a", sources=[{"source": "g"}, {"source": "s"}])
        b = self._claimed_rec("srv:b", sources=[{"source": "g"}])
        ranked = rank_servers([b, a])
        self.assertEqual(ranked[0]["identity"], "srv:a")

    def test_identity_alphabetical_breaks_final_tie(self):
        a = self._claimed_rec("srv:alpha")
        b = self._claimed_rec("srv:beta")
        ranked = rank_servers([b, a])
        self.assertEqual(ranked[0]["identity"], "srv:alpha")
        self.assertEqual(ranked[1]["identity"], "srv:beta")

    def test_none_tier_is_last(self):
        none_rec = _rec(identity="srv:none", write_confidence="unknown")
        verified = self._verified_rec("srv:v")
        ranked = rank_servers([none_rec, verified])
        self.assertEqual(ranked[-1]["identity"], "srv:none")

    def test_sort_is_deterministic_across_two_calls(self):
        records = [
            self._verified_rec("srv:z"),
            self._claimed_rec("srv:a"),
            _rec(identity="srv:m"),
        ]
        first = rank_servers(records)
        second = rank_servers(records)
        self.assertEqual(
            [r["identity"] for r in first],
            [r["identity"] for r in second],
        )

    def test_input_not_mutated(self):
        records = [self._verified_rec("srv:v"), self._claimed_rec("srv:c")]
        original_order = [r["identity"] for r in records]
        rank_servers(records)
        self.assertEqual([r["identity"] for r in records], original_order)

    def test_annotation_tier_between_verified_and_claimed(self):
        verified = self._verified_rec("srv:v")
        annotation = _rec(
            identity="srv:ann",
            write_confidence="high",
            sources=[{"source": "glama"}],
            confidence_by_source={},
            evidence=[{"kind": "mcp_annotation", "value": "destructiveHint=true", "confidence": "high"}],
        )
        claimed = self._claimed_rec("srv:c")
        ranked = rank_servers([claimed, annotation, verified])
        identities = [r["identity"] for r in ranked]
        self.assertEqual(identities[0], "srv:v")
        self.assertEqual(identities[1], "srv:ann")
        self.assertEqual(identities[2], "srv:c")


# ---------------------------------------------------------------------------
# I9 — wilson_interval
# ---------------------------------------------------------------------------

class TestWilsonInterval(unittest.TestCase):

    def test_n_zero_returns_zero_zero(self):
        low, high = wilson_interval(0, 0)
        self.assertEqual(low, 0.0)
        self.assertEqual(high, 0.0)

    def test_plausible_interval_8_of_10(self):
        phat = 0.8
        low, high = wilson_interval(8, 10)
        self.assertLess(low, phat)
        self.assertGreater(high, phat)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)

    def test_interval_ordering_low_lt_high(self):
        low, high = wilson_interval(5, 10)
        self.assertLess(low, high)

    def test_all_successes_interval_excludes_zero(self):
        low, high = wilson_interval(10, 10)
        self.assertGreater(low, 0.5)
        self.assertEqual(high, 1.0)

    def test_no_successes_interval_excludes_one(self):
        low, high = wilson_interval(0, 10)
        self.assertEqual(low, 0.0)
        self.assertLess(high, 0.5)

    def test_custom_z_widens_interval(self):
        low_95, high_95 = wilson_interval(5, 10, z=1.96)
        low_99, high_99 = wilson_interval(5, 10, z=2.576)
        self.assertLess(low_99, low_95)
        self.assertGreater(high_99, high_95)

    def test_known_case_8_of_10_approx_bounds(self):
        """For 8/10 at 95% CI the Wilson interval is roughly [0.49, 0.96]."""
        low, high = wilson_interval(8, 10)
        self.assertGreater(low, 0.44)
        self.assertLess(low, 0.60)
        self.assertGreater(high, 0.90)
        self.assertLessEqual(high, 1.0)


# ---------------------------------------------------------------------------
# I9 — summarize
# ---------------------------------------------------------------------------

class TestSummarize(unittest.TestCase):

    def _make_coverage(self):
        return {
            "sources_attempted": ["glama"],
            "sources_succeeded": ["glama"],
            "sources_failed": [],
            "per_source": {"glama": {"pulled": 100, "known_estimate": 200, "coverage_pct": 50.0}},
            "overall_coverage_pct": 50.0,
            "notes": [],
        }

    def test_total_records_correct(self):
        records = [_rec(identity=f"srv:{i}") for i in range(5)]
        result = summarize(records, self._make_coverage(), "2026-05-31")
        self.assertEqual(result["total_records"], 5)

    def test_themes_primary_sums_to_total_records(self):
        records = [
            _rec(identity="srv:1", name="Stripe billing", description="payment gateway"),
            _rec(identity="srv:2", name="GitHub bot", description="pull request manager"),
            _rec(identity="srv:3", name="Mystery tool"),
        ]
        result = summarize(records, self._make_coverage(), "2026-05-31")
        total_primary = sum(result["themes_primary"].values())
        self.assertEqual(total_primary, len(records))

    def test_by_tier_counts_correct(self):
        verified = _rec(
            identity="srv:v",
            write_confidence="high",
            confidence_by_source={"tools": {"confidence": "high", "date": "2026-05-01"}},
        )
        claimed = _rec(
            identity="srv:c",
            write_confidence="medium",
            confidence_by_source={"catalog": {"confidence": "medium", "date": "2026-05-01"}},
        )
        none_rec = _rec(identity="srv:n", write_confidence="unknown")
        records = [verified, claimed, none_rec]
        result = summarize(records, self._make_coverage(), "2026-05-31")
        self.assertEqual(result["by_tier"]["verified_tools"], 1)
        self.assertEqual(result["by_tier"]["claimed_description"], 1)
        self.assertEqual(result["by_tier"]["none"], 1)

    def test_write_capable_total(self):
        verified = _rec(
            identity="srv:v",
            write_confidence="high",
            confidence_by_source={"tools": {"confidence": "high", "date": "2026-05-01"}},
        )
        none_rec = _rec(identity="srv:n", write_confidence="unknown")
        result = summarize([verified, none_rec], self._make_coverage(), "2026-05-31")
        self.assertEqual(result["write_capable"]["total"], 1)
        self.assertEqual(result["write_capable"]["verified_tools"], 1)

    def test_validation_passed_through_verbatim(self):
        validation = {"precision": 0.85, "recall": 0.72, "f1": 0.78}
        records = [_rec()]
        result = summarize(records, self._make_coverage(), "2026-05-31", validation=validation)
        self.assertEqual(result["validation"], validation)

    def test_validation_none_when_not_provided(self):
        result = summarize([], self._make_coverage(), "2026-05-31")
        self.assertIsNone(result["validation"])

    def test_snapshot_date_passed_through(self):
        result = summarize([], self._make_coverage(), "2026-01-15")
        self.assertEqual(result["snapshot_date"], "2026-01-15")

    def test_themes_overlap_gte_total_records_for_multi_match(self):
        """A record matching multiple themes increments themes_overlap >1 time."""
        rec = _rec(
            identity="srv:multi",
            name="Deploy and slack notifier",
            description="deploy to kubernetes and send slack alerts",
        )
        result = summarize([rec], self._make_coverage(), "2026-05-31")
        total_overlap = sum(result["themes_overlap"].values())
        self.assertGreaterEqual(total_overlap, 1)

    def test_residual_dups_included(self):
        rec = _rec(identity="srv:only")
        result = summarize([rec], self._make_coverage(), "2026-05-31")
        self.assertIn("residual_dups", result)
        self.assertIn("unique_identities", result["residual_dups"])

    def test_by_tier_includes_annotation(self):
        """annotation tier records are counted in by_tier."""
        ann_rec = _rec(
            identity="srv:ann",
            write_confidence="high",
            evidence=[{"kind": "mcp_annotation", "value": "destructiveHint=true", "confidence": "high"}],
            confidence_by_source={},
        )
        result = summarize([ann_rec], self._make_coverage(), "2026-05-31")
        self.assertEqual(result["by_tier"]["annotation"], 1)

    def test_coverage_obj_passed_through(self):
        cov = self._make_coverage()
        result = summarize([], cov, "2026-05-31")
        self.assertIs(result["coverage"], cov)


# ---------------------------------------------------------------------------
# DEFAULT_TAXONOMY integrity checks
# ---------------------------------------------------------------------------

class TestDefaultTaxonomy(unittest.TestCase):

    def test_taxonomy_is_list_of_tuples(self):
        self.assertIsInstance(DEFAULT_TAXONOMY, list)
        for item in DEFAULT_TAXONOMY:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)
            theme, keywords = item
            self.assertIsInstance(theme, str)
            self.assertIsInstance(keywords, list)

    def test_payments_is_first(self):
        self.assertEqual(DEFAULT_TAXONOMY[0][0], "payments/finance/crypto")

    def test_all_theme_names_unique(self):
        names = [t[0] for t in DEFAULT_TAXONOMY]
        self.assertEqual(len(names), len(set(names)))

    def test_all_keywords_are_strings(self):
        for _, keywords in DEFAULT_TAXONOMY:
            for kw in keywords:
                self.assertIsInstance(kw, str)


class WordBoundaryMatchingTests(unittest.TestCase):
    """Lock in the accuracy fix: short keywords must not match inside words."""

    def _themes(self, text):
        return assign_themes({"name": "", "description": text, "tags": []})["all"]

    def test_no_substring_false_positives(self):
        self.assertEqual(self._themes("A precision tool for adblocker tuning"), [])
        self.assertEqual(self._themes("a legitimate business assistant"), [])
        self.assertEqual(self._themes("control your display brightness"), [])

    def test_real_standalone_keywords_still_match(self):
        self.assertIn("devtools/git", self._themes("Manage GitHub pull requests"))
        self.assertIn("data/database", self._themes("Run SQL against your database"))
        self.assertIn("payments/finance/crypto", self._themes("Send a Stripe payment"))

    def test_multiword_and_punctuated_keywords_match(self):
        self.assertIn("code-execution", self._themes("a sandbox to run code safely"))
        self.assertIn("deploy/cloud/infra", self._themes("manage your ci/cd pipeline"))


if __name__ == "__main__":
    unittest.main()
