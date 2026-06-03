import unittest

from mcp_newsletter.frontier_report import (
    FrontierEntry,
    build_frontier,
    radar_age_days,
    ranked_section,
    render_board,
    render_digest,
    render_teaching_artifact,
    select_alerts,
    weekly_delta,
)
from mcp_newsletter.models import ToolRecord
from mcp_newsletter.registries.base import RegistryServerRecord


def _rec(ident, tier_kind, *, power_desc="send a message", recency="2026-05-01",
         conf="high", tools=None):
    ev = [{"kind": tier_kind, "value": "x", "confidence": "high"}] if tier_kind else []
    return RegistryServerRecord(
        identity=ident, name=ident, description=power_desc, write_confidence=conf,
        evidence=ev, sources=[{"source": "official", "last_updated": recency}],
        tools=tools or [])


class BuildFrontierTests(unittest.TestCase):
    def test_sections_by_evidence_tier(self):
        records = {
            "v": _rec("v", "tool_text"),                 # headline
            "d": _rec("d", "declared_manifest"),         # headline
            "c": _rec("c", "registry_description"),      # emerging (claimed)
        }
        grok = {"k1": {"name": "ViralOne", "peak_engagement": 5000,
                       "why_viral": "5k likes", "source_url": "https://x/y",
                       "capability": "send", "last_seen": "2026-05-30"}}
        entries = build_frontier(records, grok)
        by_section = {}
        for e in entries:
            by_section.setdefault(e.section, []).append(e.identity)
        self.assertEqual(set(by_section["headline"]), {"v", "d"})
        self.assertEqual(by_section["emerging"], ["c"])
        self.assertEqual(by_section["viral"], ["grok:k1"])

    def test_no_write_signal_excluded(self):
        records = {"n": _rec("n", None, power_desc="reads weather", conf="unknown")}
        self.assertEqual(build_frontier(records, {}), [])


class RankingTests(unittest.TestCase):
    def test_headline_outranks_by_tier_then_power_then_recency(self):
        records = {
            "weak": _rec("weak", "declared_manifest", power_desc="reads stuff",
                         recency="2026-05-30"),                       # low power
            "strong": _rec("strong", "tool_text", power_desc="charge a card",
                           recency="2026-01-01"),                     # verified + high power
        }
        entries = build_frontier(records, {})
        ranked = ranked_section(entries, "headline")
        self.assertEqual(ranked[0].identity, "strong")  # verified+high beats declared+low

    def test_viral_ranked_by_engagement(self):
        grok = {
            "a": {"name": "A", "peak_engagement": 100, "last_seen": "2026-05-30"},
            "b": {"name": "B", "peak_engagement": 9000, "last_seen": "2026-05-30"},
        }
        entries = build_frontier({}, grok)
        ranked = ranked_section(entries, "viral")
        self.assertEqual([e.name for e in ranked], ["B", "A"])

    def test_low_power_viral_never_enters_headline(self):
        # a 50k-like viral item stays in viral; a verified write stays headline
        grok = {"v": {"name": "Hype", "peak_engagement": 50000, "last_seen": "2026-05-30"}}
        records = {"r": _rec("r", "tool_text", power_desc="charge a card")}
        entries = build_frontier(records, grok)
        headline_ids = [e.identity for e in ranked_section(entries, "headline")]
        self.assertEqual(headline_ids, ["r"])
        self.assertNotIn("grok:v", headline_ids)


class StalenessTests(unittest.TestCase):
    def test_age_from_freshest_last_seen(self):
        grok = {"a": {"last_seen": "2026-05-25"}, "b": {"last_seen": "2026-05-28"}}
        self.assertEqual(radar_age_days(grok, "2026-05-30"), 2)

    def test_empty_radar_is_none(self):
        self.assertIsNone(radar_age_days({}, "2026-05-30"))

    def test_board_prints_stale_warning(self):
        grok = {"a": {"last_seen": "2026-05-01"}}  # 29 days old
        board = render_board([], "2026-05-30", grok)
        self.assertIn("stale", board.lower())

    def test_board_empty_radar_warning(self):
        board = render_board([], "2026-05-30", {})
        self.assertIn("radar empty", board.lower())


class DeltaTests(unittest.TestCase):
    def test_new_newly_verified_and_risen(self):
        prior = [
            {"identity": "a", "name": "A", "evidence_tier": "claimed_description",
             "power_tier": "high", "section": "emerging"},
            {"identity": "v", "name": "V", "section": "viral", "engagement": 100},
        ]
        current = [
            {"identity": "a", "name": "A", "evidence_tier": "verified_tools",
             "power_tier": "high", "section": "headline"},          # newly verified
            {"identity": "b", "name": "B", "evidence_tier": "tool_text",
             "power_tier": "high", "section": "headline"},          # new
            {"identity": "v", "name": "V", "section": "viral", "engagement": 5000},  # risen
        ]
        delta = weekly_delta(current, prior)
        self.assertEqual([d["identity"] for d in delta["new"]], ["b"])
        self.assertEqual([d["identity"] for d in delta["newly_verified"]], ["a"])
        self.assertEqual([d["identity"] for d in delta["risen"]], ["v"])


class AlertTests(unittest.TestCase):
    def test_new_high_power_headline_alerts(self):
        records = {
            "new_hi": _rec("new_hi", "tool_text", power_desc="charge a card"),
            "new_lo": _rec("new_lo", "tool_text", power_desc="reads weather"),
            "old_hi": _rec("old_hi", "tool_text", power_desc="deploy to prod"),
        }
        entries = build_frontier(records, {})
        alerts = select_alerts(entries, prior_identities={"old_hi"})
        ids = {e.identity for e in alerts}
        self.assertIn("new_hi", ids)
        self.assertNotIn("new_lo", ids)   # low power excluded
        self.assertNotIn("old_hi", ids)   # already known excluded


class TeachingTests(unittest.TestCase):
    def test_groups_by_action_class_with_prompts(self):
        records = {"s": _rec("s", "tool_text", power_desc="send an email",
                             tools=[ToolRecord(provider="r", server_id="s",
                                               name="send_email", native_surface="r",
                                               description="Send")])}
        art = render_teaching_artifact(build_frontier(records, {}), "2026-05-30")
        self.assertIn("Write Edition", art)
        self.assertIn("Comms", art)
        self.assertIn("send email", art.lower())


class OrchestratorTests(unittest.TestCase):
    def test_board_written_and_digest_idempotent(self):
        import tempfile
        from pathlib import Path
        from mcp_newsletter.frontier_report import run_frontier_report
        from mcp_newsletter.registry_state import RegistryMeta

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "current").mkdir(parents=True)
            records = {"v": _rec("v", "tool_text", power_desc="charge a card")}
            meta = RegistryMeta()

            r1 = run_frontier_report(root, "2026-05-30", records, meta)
            self.assertTrue((root / "data" / "current" / "WRITE_FRONTIER_NOW.md").exists())
            self.assertTrue((root / "data" / "current" / "write_frontier_current.json").exists())
            self.assertTrue(r1["digest_due"])                  # first run: no prior digest
            self.assertEqual(meta.last_frontier_digest, "2026-05-30")
            # v is new + high-power + verified -> alert
            self.assertIn("v", {e.identity for e in r1["alerts"]})

            # next day: digest NOT due again (within 7d), and v no longer "new"
            r2 = run_frontier_report(root, "2026-05-31", records, meta)
            self.assertFalse(r2["digest_due"])
            self.assertEqual(meta.last_frontier_digest, "2026-05-30")
            self.assertEqual(r2["alerts"], [])

            # 8 days later: digest due again
            r3 = run_frontier_report(root, "2026-06-07", records, meta)
            self.assertTrue(r3["digest_due"])
            self.assertEqual(meta.last_frontier_digest, "2026-06-07")


if __name__ == "__main__":
    unittest.main()
