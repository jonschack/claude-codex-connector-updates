import unittest

from mcp_newsletter.frontier import ATTENTION_CAP, freshness, score


class FreshnessTests(unittest.TestCase):
    def test_recent_is_high_old_is_low(self):
        self.assertAlmostEqual(freshness("2026-05-30", "2026-05-30"), 1.0, places=3)
        self.assertEqual(freshness("", "2026-05-30"), 0.0)          # unknown -> 0
        self.assertEqual(freshness("2020-01-01", "2026-05-30"), 0.0)  # ancient -> 0 (backfill)

    def test_monotonic_decay(self):
        a = freshness("2026-05-29", "2026-05-30")
        b = freshness("2026-04-30", "2026-05-30")
        self.assertGreater(a, b)


class ScoreLexicographicTests(unittest.TestCase):
    def _s(self, tier, power, fresh=0.5, conf="high", corroboration=1):
        return score(tier, power, fresh, conf, corroboration=corroboration)

    def test_evidence_tier_dominates_power_and_recency(self):
        # a verified+low+stale tool beats a declared+high+fresh tool: tier dominates
        verified_low = self._s("verified_tools", "low", fresh=0.0)
        declared_high = self._s("declared_manifest", "high", fresh=1.0)
        self.assertGreater(verified_low, declared_high)

    def test_power_dominates_recency_within_tier(self):
        high_stale = self._s("verified_tools", "high", fresh=0.0)
        low_fresh = self._s("verified_tools", "low", fresh=1.0)
        self.assertGreater(high_stale, low_fresh)

    def test_recency_breaks_ties_within_band(self):
        fresh = self._s("verified_tools", "high", fresh=1.0)
        stale = self._s("verified_tools", "high", fresh=0.0)
        self.assertGreater(fresh, stale)

    def test_low_confidence_is_damped_below_high_confidence(self):
        hi = self._s("verified_tools", "high", conf="high")
        lo = self._s("verified_tools", "high", conf="low")
        self.assertGreater(hi, lo)

    def test_attention_only_reorders_within_band(self):
        # corroboration bumps score but never enough to cross a power band
        base = self._s("verified_tools", "medium", fresh=0.5, corroboration=1)
        corrob = self._s("verified_tools", "medium", fresh=0.5, corroboration=3)
        high_band = self._s("verified_tools", "high", fresh=0.0, corroboration=1)
        self.assertGreater(corrob, base)            # attention helps
        self.assertGreater(high_band, corrob)       # but never crosses the band
        self.assertLessEqual((corrob - base), ATTENTION_CAP * 10 + 1e-9)


class RankInversionGoldenTests(unittest.TestCase):
    def test_high_power_new_outranks_everything_lower(self):
        # the headline case: a fresh verified high-power tool must top the board
        top = score("verified_tools", "high", 1.0, "high")
        others = [
            score("verified_tools", "low", 1.0, "high"),
            score("annotation", "high", 1.0, "high"),
            score("declared_manifest", "high", 1.0, "high"),
            score("claimed_description", "high", 1.0, "high"),
        ]
        self.assertTrue(all(top > o for o in others))


if __name__ == "__main__":
    unittest.main()
