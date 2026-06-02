import unittest

from mcp_newsletter.health import evaluate_source_health, run_drop_alert, summarize_health


class HealthTests(unittest.TestCase):
    def test_empty_healthy_source_is_empty(self):
        h = {x.source: x for x in evaluate_source_health({"official": 0}, {"official": 100})}
        self.assertEqual(h["official"].status, "empty")

    def test_below_floor_is_degraded(self):
        h = {x.source: x for x in evaluate_source_health({"claude": 30}, {"claude": 200})}
        self.assertEqual(h["claude"].status, "degraded")

    def test_above_floor_is_ok(self):
        h = {x.source: x for x in evaluate_source_health({"glama": 24000}, {"glama": 1000})}
        self.assertEqual(h["glama"].status, "ok")

    def test_unknown_floor_only_flags_when_empty(self):
        h = {x.source: x for x in evaluate_source_health({"newsrc": 0}, {})}
        self.assertEqual(h["newsrc"].status, "empty")

    def test_run_drop_alert_fires_on_big_drop(self):
        self.assertIsNotNone(run_drop_alert(100, 1000, 50.0))

    def test_run_drop_alert_silent_without_prior(self):
        self.assertIsNone(run_drop_alert(100, None, 50.0))

    def test_run_drop_alert_silent_on_growth(self):
        self.assertIsNone(run_drop_alert(1000, 900, 50.0))

    def test_summarize_marks_degraded_and_builds_alert(self):
        s = summarize_health(
            {"official": 0, "glama": 24000},
            {"official": 100, "glama": 1000},
            total_now=24000,
            total_prev=50000,
            drop_pct=50.0,
        )
        self.assertTrue(s["degraded"])
        self.assertIn("official", s["alert"])

    def test_summarize_healthy_run_is_clean(self):
        s = summarize_health(
            {"glama": 24000},
            {"glama": 1000},
            total_now=24000,
            total_prev=24000,
            drop_pct=50.0,
        )
        self.assertFalse(s["degraded"])
        self.assertIsNone(s["alert"])


if __name__ == "__main__":
    unittest.main()
