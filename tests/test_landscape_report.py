"""
Tests for Loop 3: I3 (sample_records) and I11 (landscape_report, CLI landscape subcommand).

All tests are offline: no network, no datetime.now(), no global random state.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.landscape_report import load_snapshot, append_history, latest_prior, build_report


# ---------------------------------------------------------------------------
# Helpers: build minimal record dicts
# ---------------------------------------------------------------------------

def _rec(
    identity: str = "srv:test",
    name: str = "Test Server",
    description: str = "",
    repo_url: str = "",
    remote_url: str = "",
    sources=None,
    write_confidence: str = "unknown",
    evidence=None,
    confidence_by_source=None,
    tags=None,
) -> dict:
    return {
        "identity": identity,
        "name": name,
        "description": description,
        "repo_url": repo_url,
        "remote_url": remote_url,
        "sources": sources or [],
        "capabilities": [],
        "tags": tags or [],
        "write_confidence": write_confidence,
        "evidence": evidence or [],
        "confidence_by_source": confidence_by_source or {},
    }


def _verified_rec(identity: str, write_confidence: str = "high") -> dict:
    return _rec(
        identity=identity,
        write_confidence=write_confidence,
        confidence_by_source={"tools": {"confidence": write_confidence, "date": "2026-05-31"}},
    )


def _claimed_rec(identity: str, write_confidence: str = "medium") -> dict:
    return _rec(
        identity=identity,
        write_confidence=write_confidence,
        confidence_by_source={"catalog": {"confidence": write_confidence, "date": "2026-05-31"}},
    )


# ---------------------------------------------------------------------------
# Fix 1 — _effective_known_totals env-override tests
# ---------------------------------------------------------------------------

class TestEffectiveKnownTotals(unittest.TestCase):

    def setUp(self):
        from mcp_newsletter.landscape_report import _effective_known_totals, KNOWN_TOTALS
        self._effective_known_totals = _effective_known_totals
        self.KNOWN_TOTALS = KNOWN_TOTALS

    def test_bad_json_env_returns_default(self):
        """MCP_NEWSLETTER_KNOWN_TOTALS set to bad JSON must not raise; returns default."""
        with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_KNOWN_TOTALS": "{bad json"}):
            result = self._effective_known_totals()
        self.assertEqual(result, dict(self.KNOWN_TOTALS))

    def test_valid_json_override_merges(self):
        """Valid JSON override merges/overrides the defaults."""
        override = json.dumps({"glama": 99999, "new_source": 1234})
        with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_KNOWN_TOTALS": override}):
            result = self._effective_known_totals()
        self.assertEqual(result["glama"], 99999)
        self.assertEqual(result["new_source"], 1234)
        # Keys not in override retain defaults
        self.assertEqual(result["official"], self.KNOWN_TOTALS["official"])

    def test_empty_env_returns_default(self):
        """Absent env var returns default KNOWN_TOTALS unchanged."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MCP_NEWSLETTER_KNOWN_TOTALS", None)
            result = self._effective_known_totals()
        self.assertEqual(result, dict(self.KNOWN_TOTALS))


# ---------------------------------------------------------------------------
# I3 — sample_records tests
# ---------------------------------------------------------------------------

class TestSampleRecords(unittest.TestCase):

    def setUp(self):
        from mcp_newsletter.landscape import sample_records
        self.sample_records = sample_records

    # --- determinism ---

    def test_same_seed_produces_same_result(self):
        records = [_rec(identity=f"srv:{i}") for i in range(20)]
        first = self.sample_records(records, 7, seed=99)
        second = self.sample_records(records, 7, seed=99)
        self.assertEqual(
            [r["identity"] for r in first],
            [r["identity"] for r in second],
        )

    def test_different_seed_may_produce_different_result(self):
        """Different seeds should (with very high probability) produce different samples."""
        records = [_rec(identity=f"srv:{i}") for i in range(30)]
        r1 = self.sample_records(records, 10, seed=1)
        r2 = self.sample_records(records, 10, seed=2)
        # With 30 records and n=10, probability of identical sample is astronomically small
        self.assertNotEqual(
            [r["identity"] for r in r1],
            [r["identity"] for r in r2],
        )

    def test_determinism_not_affected_by_outside_random_state(self):
        """seeded local Random must not be influenced by global random module state."""
        import random as _random
        records = [_rec(identity=f"srv:{i}") for i in range(20)]
        _random.seed(42)
        first = self.sample_records(records, 7, seed=99)
        _random.seed(12345)
        second = self.sample_records(records, 7, seed=99)
        self.assertEqual(
            [r["identity"] for r in first],
            [r["identity"] for r in second],
        )

    # --- n >= len returns all ---

    def test_n_equals_len_returns_all_records(self):
        records = [_rec(identity=f"srv:{i}") for i in range(5)]
        result = self.sample_records(records, 5, seed=1)
        self.assertEqual(len(result), 5)
        result_ids = {r["identity"] for r in result}
        self.assertEqual(result_ids, {f"srv:{i}" for i in range(5)})

    def test_n_greater_than_len_returns_all_records(self):
        records = [_rec(identity=f"srv:{i}") for i in range(5)]
        result = self.sample_records(records, 100, seed=1)
        self.assertEqual(len(result), 5)

    def test_n_zero_returns_empty(self):
        records = [_rec(identity=f"srv:{i}") for i in range(5)]
        result = self.sample_records(records, 0, seed=1)
        self.assertEqual(result, [])

    def test_empty_input_returns_empty(self):
        result = self.sample_records([], 5, seed=1)
        self.assertEqual(result, [])

    # --- sample is a subset ---

    def test_sample_is_subset_of_records(self):
        records = [_rec(identity=f"srv:{i}") for i in range(30)]
        result = self.sample_records(records, 10, seed=7)
        self.assertEqual(len(result), 10)
        record_ids = {r["identity"] for r in records}
        for r in result:
            self.assertIn(r["identity"], record_ids)

    def test_no_duplicates_in_sample(self):
        records = [_rec(identity=f"srv:{i}") for i in range(30)]
        result = self.sample_records(records, 15, seed=3)
        ids = [r["identity"] for r in result]
        self.assertEqual(len(ids), len(set(ids)))

    # --- stratified proportionality ---

    def test_stratified_roughly_proportional(self):
        """Stratified sample should roughly reflect bucket proportions."""
        # 60 "type_a" records and 40 "type_b" records
        records = (
            [_rec(identity=f"a:{i}", tags=["type_a"]) for i in range(60)]
            + [_rec(identity=f"b:{i}", tags=["type_b"]) for i in range(40)]
        )

        def key(r):
            return r["tags"][0] if r.get("tags") else "unknown"

        result = self.sample_records(records, 50, seed=42, stratify_key=key)
        self.assertEqual(len(result), 50)

        a_count = sum(1 for r in result if r["identity"].startswith("a:"))
        b_count = sum(1 for r in result if r["identity"].startswith("b:"))
        # Expected: ~30 a, ~20 b.  Allow ±3 tolerance.
        self.assertAlmostEqual(a_count, 30, delta=3)
        self.assertAlmostEqual(b_count, 20, delta=3)

    def test_stratified_deterministic(self):
        records = (
            [_rec(identity=f"a:{i}", tags=["bucket_a"]) for i in range(20)]
            + [_rec(identity=f"b:{i}", tags=["bucket_b"]) for i in range(20)]
        )

        def key(r):
            return r["tags"][0]

        r1 = self.sample_records(records, 10, seed=77, stratify_key=key)
        r2 = self.sample_records(records, 10, seed=77, stratify_key=key)
        self.assertEqual(
            [r["identity"] for r in r1],
            [r["identity"] for r in r2],
        )

    def test_stratified_result_sorted_by_identity(self):
        """Result must be sorted by identity for full determinism."""
        records = (
            [_rec(identity=f"z:{i}", tags=["bucket_z"]) for i in range(5)]
            + [_rec(identity=f"a:{i}", tags=["bucket_a"]) for i in range(5)]
        )

        def key(r):
            return r["tags"][0]

        result = self.sample_records(records, 6, seed=1, stratify_key=key)
        identities = [r["identity"] for r in result]
        self.assertEqual(identities, sorted(identities))

    def test_stratified_n_greater_than_len_returns_all(self):
        records = (
            [_rec(identity=f"a:{i}", tags=["x"]) for i in range(3)]
            + [_rec(identity=f"b:{i}", tags=["y"]) for i in range(3)]
        )

        def key(r):
            return r["tags"][0]

        result = self.sample_records(records, 100, seed=1, stratify_key=key)
        self.assertEqual(len(result), 6)

    def test_stratified_single_bucket(self):
        """All records in one bucket → behaves like uniform sample."""
        records = [_rec(identity=f"srv:{i}", tags=["only"]) for i in range(10)]

        def key(r):
            return r["tags"][0]

        result = self.sample_records(records, 5, seed=9, stratify_key=key)
        self.assertEqual(len(result), 5)

    def test_input_not_mutated_by_sample(self):
        records = [_rec(identity=f"srv:{i}") for i in range(10)]
        original_ids = [r["identity"] for r in records]
        self.sample_records(records, 5, seed=1)
        self.assertEqual([r["identity"] for r in records], original_ids)


# ---------------------------------------------------------------------------
# I11 — run_validation tests
# ---------------------------------------------------------------------------

class TestRunValidation(unittest.TestCase):

    def setUp(self):
        from mcp_newsletter.landscape_report import run_validation
        self.run_validation = run_validation

    def _make_records(self, n_with_url: int = 5, n_without_url: int = 2) -> list:
        records = []
        for i in range(n_with_url):
            r = _rec(
                identity=f"srv:url:{i}",
                remote_url=f"https://example.com/mcp/{i}",
            )
            records.append(r)
        for i in range(n_without_url):
            r = _rec(identity=f"srv:nourl:{i}", remote_url="")
            records.append(r)
        return records

    def _fake_discover_fn(self, answers: dict):
        """
        Return a discover_fn that returns canned tools for identities in *answers*
        and [] for all others.

        answers: {identity: [tool_dict, ...]}
        """
        def discover_fn(rec: dict) -> list:
            return answers.get(rec.get("identity"), [])
        return discover_fn

    def _write_tool(self, confidence: str = "high") -> dict:
        return {"name": "write_file", "write_confidence": confidence, "evidence": []}

    def _read_tool(self, confidence: str = "low") -> dict:
        return {"name": "read_file", "write_confidence": confidence, "evidence": []}

    # --- basic shape ---

    def test_returns_required_keys(self):
        records = self._make_records(3)
        discover_fn = self._fake_discover_fn({})
        result = self.run_validation(records, sample_n=3, seed=1, discover_fn=discover_fn, run_date="2026-05-31")
        for key in ("n", "tp", "fp", "fn", "tn", "precision", "recall", "f1",
                    "accuracy", "precision_ci", "recall_ci",
                    "sample_n", "answered", "unevaluable"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_sample_n_stored_in_result(self):
        records = self._make_records(5)
        discover_fn = self._fake_discover_fn({})
        result = self.run_validation(records, sample_n=3, seed=1, discover_fn=discover_fn, run_date="2026-05-31")
        self.assertEqual(result["sample_n"], 3)

    # --- unevaluable count ---

    def test_records_without_remote_url_excluded_from_sample(self):
        """Records with no remote_url are not passed to discover_fn."""
        records = self._make_records(n_with_url=3, n_without_url=5)
        calls = []

        def counting_fn(rec):
            calls.append(rec["identity"])
            return []

        self.run_validation(records, sample_n=10, seed=1, discover_fn=counting_fn, run_date="2026-05-31")
        # Only the 3 records with URLs should ever be passed to discover_fn
        for identity in calls:
            self.assertTrue(identity.startswith("srv:url:"), f"Unexpected identity called: {identity}")

    def test_empty_tools_response_counted_as_unevaluable(self):
        records = self._make_records(n_with_url=4, n_without_url=0)
        # 2 answer, 2 return []
        answers = {
            "srv:url:0": [self._write_tool()],
            "srv:url:1": [self._read_tool()],
        }
        discover_fn = self._fake_discover_fn(answers)
        result = self.run_validation(records, sample_n=4, seed=1, discover_fn=discover_fn, run_date="2026-05-31")
        self.assertEqual(result["answered"] + result["unevaluable"], 4)
        self.assertEqual(result["unevaluable"], 2)
        self.assertEqual(result["answered"], 2)

    # --- labeled set construction ---

    def test_write_tool_response_produces_actual_write_true(self):
        """A record answered with a high-confidence write tool → actual_write=True."""
        records = [_rec(identity="srv:a", remote_url="https://example.com/a")]
        answers = {"srv:a": [self._write_tool("high")]}
        discover_fn = self._fake_discover_fn(answers)
        result = self.run_validation(records, sample_n=1, seed=1, discover_fn=discover_fn, run_date="2026-05-31")
        self.assertEqual(result["answered"], 1)
        # actual_write=True, predicted_write=False (no prior catalog confidence)
        self.assertEqual(result["fn"], 1)

    def test_description_predicted_write_correct_for_claimed_record(self):
        """A record with catalog confidence → predicted_write=True before grounding."""
        rec = _rec(
            identity="srv:claimed",
            remote_url="https://example.com/c",
            write_confidence="medium",
            confidence_by_source={"catalog": {"confidence": "medium", "date": "2026-05-31"}},
        )
        # Return a write tool → actual_write=True → TP
        answers = {"srv:claimed": [self._write_tool("high")]}
        discover_fn = self._fake_discover_fn(answers)
        result = self.run_validation([rec], sample_n=1, seed=1, discover_fn=discover_fn, run_date="2026-05-31")
        self.assertEqual(result["answered"], 1)
        self.assertEqual(result["tp"], 1)

    def test_discover_fn_exception_treated_as_unevaluable(self):
        """discover_fn raising an exception → record counted as unevaluable, not crash."""
        records = [_rec(identity="srv:err", remote_url="https://example.com/err")]

        def erroring_fn(rec):
            raise RuntimeError("network error")

        result = self.run_validation(records, sample_n=1, seed=1, discover_fn=erroring_fn, run_date="2026-05-31")
        self.assertEqual(result["unevaluable"], 1)
        self.assertEqual(result["answered"], 0)

    def test_all_unevaluable_returns_zero_precision_recall(self):
        records = self._make_records(n_with_url=3, n_without_url=0)
        discover_fn = self._fake_discover_fn({})  # no answers
        result = self.run_validation(records, sample_n=3, seed=1, discover_fn=discover_fn, run_date="2026-05-31")
        self.assertEqual(result["answered"], 0)
        self.assertEqual(result["unevaluable"], 3)
        self.assertEqual(result["precision"], 0.0)
        self.assertEqual(result["recall"], 0.0)

    def test_original_records_not_mutated_by_validation(self):
        """run_validation must not mutate the original records list."""
        records = [
            _rec(
                identity="srv:a",
                remote_url="https://example.com/a",
                confidence_by_source={},
            )
        ]
        import copy
        original = copy.deepcopy(records)
        answers = {"srv:a": [self._write_tool("high")]}
        discover_fn = self._fake_discover_fn(answers)
        self.run_validation(records, sample_n=1, seed=1, discover_fn=discover_fn, run_date="2026-05-31")
        self.assertEqual(records[0]["confidence_by_source"], original[0]["confidence_by_source"])

    def test_predicted_write_is_catalog_only_not_contaminated_by_tools(self):
        """A record with pre-existing tools evidence but catalog=unknown → predicted_write=False.

        Proves the prediction uses only the catalog/description tier, not the
        pre-existing verified_tools evidence that would inflate metrics.
        """
        # Record has a pre-existing tools entry (high confidence) but no catalog entry
        rec = _rec(
            identity="srv:tools-only",
            remote_url="https://example.com/t",
            write_confidence="high",
            confidence_by_source={
                "tools": {"confidence": "high", "date": "2026-05-31"},
                # no "catalog" key → catalog confidence is unknown
            },
        )
        # Return a write tool → actual_write=True
        answers = {"srv:tools-only": [self._write_tool("high")]}
        discover_fn = self._fake_discover_fn(answers)
        result = self.run_validation([rec], sample_n=1, seed=1, discover_fn=discover_fn, run_date="2026-05-31")
        self.assertEqual(result["answered"], 1)
        # predicted_write must be False (catalog unknown), actual_write True → FN, not TP
        self.assertEqual(result["fn"], 1)
        self.assertEqual(result["tp"], 0)


# ---------------------------------------------------------------------------
# I11 — build_report tests
# ---------------------------------------------------------------------------

class TestBuildReport(unittest.TestCase):

    def setUp(self):
        from mcp_newsletter.landscape_report import build_report
        self.build_report = build_report

    def _minimal_summary(self, sources=None):
        sources = sources or ["glama"]
        return {
            "enabled_sources": sources,
            "source_ok": {s: True for s in sources},
            "per_source": {s: 5 for s in sources},
            "per_source_raw": {},
            "issues": [],
        }

    def _small_records(self):
        return [
            _verified_rec("srv:v1", "high"),
            _verified_rec("srv:v2", "medium"),
            _claimed_rec("srv:c1", "medium"),
            _claimed_rec("srv:c2", "high"),
            _rec(identity="srv:none", write_confidence="unknown"),
        ]

    # --- markdown contains required sections ---

    def test_markdown_contains_methodology(self):
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIn("Methodology", md)

    def test_markdown_contains_per_tier_counts(self):
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        # Must mention all three tier names
        self.assertIn("verified_tools", md)
        self.assertIn("annotation", md)
        self.assertIn("claimed_description", md)

    def test_markdown_labels_claimed_description_as_unverified(self):
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        # The phrase "claimed (unverified)" must appear for claimed_description entries
        self.assertIn("claimed (unverified)", md)

    def test_markdown_does_not_blend_tiers_in_headline(self):
        """There must be per-tier breakdown; no single blended 'write-capable' number in isolation."""
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        # The table should break out by tier
        self.assertIn("| Evidence Tier |", md)

    def test_markdown_contains_theme_section(self):
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIn("Theme", md)

    def test_markdown_contains_ranked_servers(self):
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIn("Ranked", md)

    # --- metrics dict shape ---

    def test_metrics_has_by_tier(self):
        records = self._small_records()
        _, metrics = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIn("by_tier", metrics)
        for tier in ("verified_tools", "annotation", "claimed_description", "none"):
            self.assertIn(tier, metrics["by_tier"])

    def test_metrics_has_coverage(self):
        records = self._small_records()
        _, metrics = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIn("coverage", metrics)
        self.assertIn("sources_succeeded", metrics["coverage"])

    def test_metrics_validation_is_none_when_not_provided(self):
        records = self._small_records()
        _, metrics = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIsNone(metrics["validation"])

    def test_metrics_validation_passed_through(self):
        records = self._small_records()
        fake_validation = {
            "n": 5, "tp": 3, "fp": 1, "fn": 1, "tn": 0,
            "precision": 0.75, "recall": 0.75, "f1": 0.75, "accuracy": 0.6,
            "precision_ci": (0.3, 0.95), "recall_ci": (0.3, 0.95),
            "sample_n": 5, "answered": 5, "unevaluable": 0,
        }
        _, metrics = self.build_report(
            records, self._minimal_summary(), "2026-05-31", validation=fake_validation
        )
        self.assertEqual(metrics["validation"], fake_validation)

    def test_validation_section_in_markdown_when_provided(self):
        records = self._small_records()
        fake_validation = {
            "n": 5, "tp": 3, "fp": 1, "fn": 1, "tn": 0,
            "precision": 0.75, "recall": 0.75, "f1": 0.75, "accuracy": 0.6,
            "precision_ci": (0.3, 0.95), "recall_ci": (0.3, 0.95),
            "sample_n": 5, "answered": 5, "unevaluable": 0,
        }
        md, _ = self.build_report(
            records, self._minimal_summary(), "2026-05-31", validation=fake_validation
        )
        self.assertIn("Classifier Validation", md)
        self.assertIn("Precision", md)
        self.assertIn("Recall", md)

    def test_by_tier_counts_correct_in_metrics(self):
        records = self._small_records()  # 2 verified, 0 annotation, 2 claimed, 1 none
        _, metrics = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertEqual(metrics["by_tier"]["verified_tools"], 2)
        self.assertEqual(metrics["by_tier"]["claimed_description"], 2)
        self.assertEqual(metrics["by_tier"]["none"], 1)
        self.assertEqual(metrics["by_tier"]["annotation"], 0)

    def test_write_capable_not_blended(self):
        """write_capable must have per-tier breakdown, not just a single total."""
        records = self._small_records()
        _, metrics = self.build_report(records, self._minimal_summary(), "2026-05-31")
        wc = metrics["write_capable"]
        self.assertIn("verified_tools", wc)
        self.assertIn("annotation", wc)
        self.assertIn("claimed_description", wc)
        self.assertIn("total", wc)

    def test_top_n_respected(self):
        records = [_verified_rec(f"srv:v{i}") for i in range(20)]
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31", top_n=5)
        # The top-5 table should have exactly 5 data rows
        import re as _re
        # Rank rows look like "| 5 | srv:v5 | ..."
        rank_rows = _re.findall(r"^\| (\d+) \|", md, _re.MULTILINE)
        self.assertIn("5", rank_rows)
        self.assertNotIn("6", rank_rows)

    def test_snapshot_date_in_markdown(self):
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-01-15")
        self.assertIn("2026-01-15", md)

    def test_empty_records_produces_valid_output(self):
        md, metrics = self.build_report([], self._minimal_summary(), "2026-05-31")
        self.assertIsInstance(md, str)
        self.assertIn("Methodology", md)
        self.assertEqual(metrics["total_records"], 0)

    def test_remote_scope_caveat_present_when_validation_provided(self):
        """The report must include the remote-scope caveat whenever validation is present."""
        records = self._small_records()
        fake_validation = {
            "n": 5, "tp": 3, "fp": 1, "fn": 1, "tn": 0,
            "precision": 0.75, "recall": 0.75, "f1": 0.75, "accuracy": 0.6,
            "precision_ci": (0.3, 0.95), "recall_ci": (0.3, 0.95),
            "sample_n": 5, "answered": 4, "unevaluable": 1,
        }
        md, _ = self.build_report(
            records, self._minimal_summary(), "2026-05-31", validation=fake_validation
        )
        self.assertIn("remotely-verifiable", md)
        self.assertIn("tools/list", md)
        # Also verify answered/unevaluable counts appear in the section
        self.assertIn("4", md)   # answered
        self.assertIn("1", md)   # unevaluable

    def test_remote_scope_caveat_absent_when_no_validation(self):
        """The remote-scope caveat must NOT appear when validation is None."""
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertNotIn("remotely-verifiable", md)

    # --- Refinement 1: tier-zero explanation note ---

    def test_tier_zero_note_always_present(self):
        """The tier-zero explanation note must appear even when verified/annotation counts are 0."""
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIn("raise counts from", md)

    def test_tier_zero_note_present_when_all_tiers_zero(self):
        """Note must appear even when all records are 'none' (all counts zero)."""
        records = [_rec(identity="srv:none1"), _rec(identity="srv:none2")]
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIn("raise counts from", md)

    # --- Refinement 2: adjusted-unique estimate ---

    def test_adjusted_unique_estimate_present(self):
        """The adjusted unique estimate must appear in the Deduplication section."""
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertIn("Adjusted unique estimate:", md)
        self.assertIn("after removing suspected duplicates", md)

    def test_adjusted_unique_estimate_math(self):
        """Adjusted unique estimate = unique_identities - suspected_extra_records."""
        # Build records with known identities and one that would produce a suspected dup.
        # We need residual_dups to have non-zero suspected_extra_records.
        # Use a record set where the dedup logic yields a known residual dup.
        # Import summarize/coverage to inspect the residual_dups metric directly.
        from mcp_newsletter.landscape_report import build_report
        from mcp_newsletter.landscape import coverage

        # Create 5 records where one identity group has 2 records (a suspected dup cluster).
        records = [
            _rec(identity="srv:a", repo_url="https://github.com/owner/repo"),
            _rec(identity="srv:a", repo_url="https://github.com/owner/repo"),  # dup of above
            _rec(identity="srv:b"),
            _rec(identity="srv:c"),
            _rec(identity="srv:d"),
        ]
        md, metrics = build_report(records, self._minimal_summary(), "2026-05-31")
        rdups = metrics.get("residual_dups") or {}
        unique_identities = rdups.get("unique_identities", 0)
        suspected_extra = rdups.get("suspected_extra_records", 0)
        expected = unique_identities - suspected_extra
        # The exact text of the adjusted figure must appear in the markdown
        self.assertIn(f"Adjusted unique estimate: {expected}", md)

    # --- Refinement 3: small-sample CI caveat ---

    def test_small_sample_caveat_present_when_validation_provided(self):
        """Labeled-set size sentence must appear in the report when validation is given."""
        records = self._small_records()
        fake_validation = {
            "n": 10, "tp": 4, "fp": 1, "fn": 2, "tn": 3,
            "precision": 0.80, "recall": 0.67, "f1": 0.73, "accuracy": 0.70,
            "precision_ci": (0.45, 0.97), "recall_ci": (0.29, 0.93),
            "sample_n": 10, "answered": 7, "unevaluable": 3,
        }
        md, _ = self.build_report(
            records, self._minimal_summary(), "2026-05-31", validation=fake_validation
        )
        self.assertIn("Labeled-set size: 7 servers", md)
        self.assertIn("--validate-sample", md)

    def test_small_sample_caveat_answered_zero_does_not_crash(self):
        """When answered=0, the caveat must still render without error."""
        records = self._small_records()
        fake_validation = {
            "n": 5, "tp": 0, "fp": 0, "fn": 0, "tn": 0,
            "precision": 0.0, "recall": 0.0, "f1": 0.0, "accuracy": 0.0,
            "precision_ci": (0.0, 0.0), "recall_ci": (0.0, 0.0),
            "sample_n": 5, "answered": 0, "unevaluable": 5,
        }
        md, _ = self.build_report(
            records, self._minimal_summary(), "2026-05-31", validation=fake_validation
        )
        self.assertIn("Labeled-set size: 0 servers", md)

    def test_small_sample_caveat_absent_when_no_validation(self):
        """The labeled-set size sentence must NOT appear when validation is None."""
        records = self._small_records()
        md, _ = self.build_report(records, self._minimal_summary(), "2026-05-31")
        self.assertNotIn("Labeled-set size:", md)


# ---------------------------------------------------------------------------
# I11 — CLI landscape subcommand tests (offline, --skip-network)
# ---------------------------------------------------------------------------

class TestLandscapeCLI(unittest.TestCase):
    """Test the 'landscape' CLI subcommand with --skip-network.

    A tiny fixture snapshot is written to a tmpdir; the CLI must exit 0,
    write LANDSCAPE_REPORT.md and landscape_metrics.json, with no network.
    """

    def _make_fixture(self, tmpdir: Path) -> None:
        """Write a minimal registry_state.jsonl + registry_summary.json."""
        data_dir = tmpdir / "data" / "current"
        data_dir.mkdir(parents=True)

        # 3 records
        records = [
            _verified_rec("srv:v1", "high"),
            _claimed_rec("srv:c1", "medium"),
            _rec(identity="srv:n1", write_confidence="unknown"),
        ]
        state_path = data_dir / "registry_state.jsonl"
        with open(state_path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "enabled_sources": ["glama"],
            "source_ok": {"glama": True},
            "per_source": {"glama": 3},
            "per_source_raw": {},
            "issues": [],
        }
        summary_path = data_dir / "registry_summary.json"
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh)

    def test_cli_exits_zero_with_skip_network(self):
        from mcp_newsletter.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_fixture(root)
            ret = main(["landscape", "--root", str(root), "--skip-network"])
            self.assertEqual(ret, 0)

    def test_cli_writes_report_file(self):
        from mcp_newsletter.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_fixture(root)
            main(["landscape", "--root", str(root), "--skip-network"])
            report_path = root / "data" / "current" / "LANDSCAPE_REPORT.md"
            self.assertTrue(report_path.exists(), "LANDSCAPE_REPORT.md not written")
            content = report_path.read_text(encoding="utf-8")
            self.assertGreater(len(content), 100)

    def test_cli_writes_metrics_file(self):
        from mcp_newsletter.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_fixture(root)
            main(["landscape", "--root", str(root), "--skip-network"])
            metrics_path = root / "data" / "current" / "landscape_metrics.json"
            self.assertTrue(metrics_path.exists(), "landscape_metrics.json not written")
            with open(metrics_path, "r", encoding="utf-8") as fh:
                metrics = json.load(fh)
            self.assertIn("by_tier", metrics)
            self.assertIn("coverage", metrics)

    def test_cli_report_markdown_has_required_sections(self):
        from mcp_newsletter.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_fixture(root)
            main(["landscape", "--root", str(root), "--skip-network"])
            report_path = root / "data" / "current" / "LANDSCAPE_REPORT.md"
            content = report_path.read_text(encoding="utf-8")
            self.assertIn("Methodology", content)
            self.assertIn("verified_tools", content)
            self.assertIn("claimed (unverified)", content)

    def test_cli_skip_network_skips_validation(self):
        """Even when --validate-sample is given, --skip-network must skip validation."""
        from mcp_newsletter.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_fixture(root)
            # Should not crash or contact network even with --validate-sample
            ret = main([
                "landscape", "--root", str(root),
                "--skip-network",
                "--validate-sample", "5",
            ])
            self.assertEqual(ret, 0)
            metrics_path = root / "data" / "current" / "landscape_metrics.json"
            with open(metrics_path, "r", encoding="utf-8") as fh:
                metrics = json.load(fh)
            # validation must be null when --skip-network is set
            self.assertIsNone(metrics.get("validation"))

    def test_cli_with_date_flag(self):
        from mcp_newsletter.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_fixture(root)
            ret = main(["landscape", "--root", str(root), "--skip-network", "--date", "2026-01-15"])
            self.assertEqual(ret, 0)
            report_path = root / "data" / "current" / "LANDSCAPE_REPORT.md"
            content = report_path.read_text(encoding="utf-8")
            self.assertIn("2026-01-15", content)

    def test_cli_with_top_n_flag(self):
        from mcp_newsletter.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_fixture(root)
            ret = main(["landscape", "--root", str(root), "--skip-network", "--top-n", "2"])
            self.assertEqual(ret, 0)
            report_path = root / "data" / "current" / "LANDSCAPE_REPORT.md"
            content = report_path.read_text(encoding="utf-8")
            # The ranked-servers table header should say "Top 2 Servers"
            self.assertIn("Top 2 Servers", content)
            # The ranked table should have a rank-2 row but NOT a rank-3 row
            # (rows in the ranked table look like "| 2 | srv:..." not just "| 2 |")
            import re as _re
            rank_rows = _re.findall(r"^\| (\d+) \|", content, _re.MULTILINE)
            self.assertIn("2", rank_rows)
            self.assertNotIn("3", rank_rows)

    def test_cli_missing_snapshot_exits_nonzero_with_message(self):
        """landscape on a tmpdir with no data/current/ must exit 1 and print a helpful message."""
        import io
        from mcp_newsletter.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Do NOT call _make_fixture — there is no snapshot here
            captured = io.StringIO()
            with mock.patch("sys.stdout", captured):
                ret = main(["landscape", "--root", str(root), "--skip-network"])
            self.assertEqual(ret, 1)
            output = captured.getvalue()
            self.assertIn("data/current", output)
            self.assertIn("update", output)
            # No traceback in the output
            self.assertNotIn("Traceback", output)
            self.assertNotIn("FileNotFoundError", output)


# ---------------------------------------------------------------------------
# UnifiedLoader — load_snapshot with include_vendor
# ---------------------------------------------------------------------------

class UnifiedLoaderTests(unittest.TestCase):
    def _write_snapshot(self, tmp, with_vendor=True):
        cur = Path(tmp) / "data" / "current"; cur.mkdir(parents=True)
        (cur / "registry_state.jsonl").write_text(
            json.dumps({"identity": "io.x/a", "name": "A", "description": "",
                        "repo_url": "", "remote_url": "", "sources": [{"source": "official"}],
                        "capabilities": [], "tags": [], "write_confidence": "unknown",
                        "evidence": [], "confidence_by_source": {}}) + "\n")
        (cur / "registry_summary.json").write_text(json.dumps(
            {"run_date": "2026-05-31", "enabled_sources": ["official"], "source_ok": {"official": True},
             "per_source": {"official": 1}, "per_source_raw": {"official": 1}, "issues": []}))
        if with_vendor:
            (cur / "servers.json").write_text(json.dumps([
                {"provider": "claude", "server_id": "linear", "name": "Linear",
                 "description": "create issues", "capabilities": ["Read & write"],
                 "write_confidence": "high", "evidence": [], "remote_url": "",
                 "source_urls": [], "native_surface": "connector", "transport": "mcp", "metadata": {}}]))

    def test_includes_vendor_records_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_snapshot(tmp)
            recs, summ = load_snapshot(Path(tmp), include_vendor=True)
        idents = {r["identity"] for r in recs}
        self.assertIn("io.x/a", idents)
        self.assertIn("claude:linear", idents)

    def test_excludes_vendor_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_snapshot(tmp)
            recs, _ = load_snapshot(Path(tmp))
        self.assertEqual([r["identity"] for r in recs], ["io.x/a"])

    def test_include_vendor_with_no_servers_json_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_snapshot(tmp, with_vendor=False)
            recs, _ = load_snapshot(Path(tmp), include_vendor=True)
        self.assertEqual([r["identity"] for r in recs], ["io.x/a"])

    def test_malformed_servers_json_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_snapshot(tmp, with_vendor=False)
            (Path(tmp) / "data" / "current" / "servers.json").write_text("not json{")
            recs, _ = load_snapshot(Path(tmp), include_vendor=True)
        self.assertEqual([r["identity"] for r in recs], ["io.x/a"])  # registry intact, vendor skipped

    def test_run_date_falls_back_to_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_snapshot(tmp)  # summary run_date = 2026-05-31, vendor 'high'
            recs, _ = load_snapshot(Path(tmp), include_vendor=True)  # no explicit run_date
        linear = next(r for r in recs if r["identity"] == "claude:linear")
        self.assertEqual(linear["confidence_by_source"]["catalog"]["date"], "2026-05-31")


# ---------------------------------------------------------------------------
# generate_landscape — reusable helper
# ---------------------------------------------------------------------------

class GenerateLandscapeTests(unittest.TestCase):
    def _snapshot(self, tmp):
        cur = Path(tmp) / "data" / "current"; cur.mkdir(parents=True)
        (cur / "registry_state.jsonl").write_text(
            json.dumps({"identity": "io.x/a", "name": "A", "description": "send messages",
                        "repo_url": "", "remote_url": "", "sources": [{"source": "official"}],
                        "capabilities": [], "tags": [], "write_confidence": "medium",
                        "evidence": [], "confidence_by_source": {"catalog": {"confidence": "medium", "date": "2026-05-31"}}}) + "\n")
        (cur / "registry_summary.json").write_text(json.dumps(
            {"run_date": "2026-05-31", "enabled_sources": ["official"], "source_ok": {"official": True},
             "per_source": {"official": 1}, "per_source_raw": {"official": 1}, "issues": []}))

    def test_generate_writes_report_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._snapshot(tmp)
            from mcp_newsletter.landscape_report import generate_landscape
            metrics = generate_landscape(Path(tmp), run_date="2026-05-31")
            cur = Path(tmp) / "data" / "current"
            self.assertTrue((cur / "LANDSCAPE_REPORT.md").exists())
            self.assertTrue((cur / "landscape_metrics.json").exists())
            self.assertEqual(metrics["total_records"], 1)
            self.assertEqual(json.loads((cur / "landscape_metrics.json").read_text())["total_records"], 1)


# ---------------------------------------------------------------------------
# History — append_history / latest_prior / build_report with prior_metrics
# ---------------------------------------------------------------------------

class HistoryTests(unittest.TestCase):
    def _metrics(self, date, verified, cov):
        return {"snapshot_date": date, "total_records": 100,
                "by_tier": {}, "write_capable": {"total": verified, "verified_tools": verified,
                "annotation": 0, "claimed_description": 0},
                "coverage": {"overall_coverage_pct": cov}, "themes_primary": {}, "themes_overlap": {},
                "residual_dups": {"unique_identities": 100, "suspected_extra_records": 0,
                                  "suspected_dup_clusters": 0, "examples": []}, "validation": None}

    def test_append_then_latest_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data" / "current").mkdir(parents=True)
            append_history(Path(tmp), self._metrics("2026-05-24", 10, 20.0))
            append_history(Path(tmp), self._metrics("2026-05-31", 14, 26.0))
            prior = latest_prior(Path(tmp), before_date="2026-05-31")
            self.assertEqual(prior["snapshot_date"], "2026-05-24")  # most recent strictly before
            self.assertIsNone(latest_prior(Path(tmp), before_date="2026-05-24"))  # nothing before first

    def test_report_shows_change_since_prior(self):
        cur = self._metrics("2026-05-31", 14, 26.0)
        prior = self._metrics("2026-05-24", 10, 20.0)
        # build_report takes records+summary+snapshot_date; pass prior via prior_metrics kwarg.
        md, _ = build_report(records=[], summary={"enabled_sources": [], "source_ok": {},
                             "per_source": {}, "per_source_raw": {}, "issues": []},
                             snapshot_date="2026-05-31", prior_metrics=prior, top_n=5)
        # NOTE: build_report computes its OWN metrics from records; to show the diff it compares
        # the CURRENT computed metrics vs prior_metrics. With empty records current verified=0.
        self.assertIn("Change since 2026-05-24", md)

    def test_report_baseline_when_no_prior(self):
        md, _ = build_report(records=[], summary={"enabled_sources": [], "source_ok": {},
                             "per_source": {}, "per_source_raw": {}, "issues": []},
                             snapshot_date="2026-05-31", prior_metrics=None, top_n=5)
        self.assertIn("baseline", md.lower())


if __name__ == "__main__":
    unittest.main()
