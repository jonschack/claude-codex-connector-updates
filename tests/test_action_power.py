import unittest

from mcp_newsletter.action_power import POWER_RANK, power_tier_for, record_power_tier
from mcp_newsletter.models import ToolRecord
from mcp_newsletter.registries.base import RegistryServerRecord


class PowerTierForTests(unittest.TestCase):
    def test_high_power_classes(self):
        self.assertEqual(power_tier_for("send a Slack message"), "high")   # comms
        self.assertEqual(power_tier_for("deploy to production"), "high")   # deploy
        self.assertEqual(power_tier_for("charge the card"), "high")        # money
        self.assertEqual(power_tier_for("run a shell command"), "high")    # system_control

    def test_medium_power_classes(self):
        self.assertEqual(power_tier_for("update a database row"), "medium")  # data_write
        self.assertEqual(power_tier_for("schedule a meeting"), "medium")     # scheduling

    def test_low_when_no_action_class(self):
        self.assertEqual(power_tier_for("shows the weather forecast"), "low")

    def test_max_power_wins(self):
        # money (high) beats data_write (medium) when both present
        self.assertEqual(power_tier_for("charge a card and update the database"), "high")

    def test_rank_order(self):
        self.assertGreater(POWER_RANK["high"], POWER_RANK["medium"])
        self.assertGreater(POWER_RANK["medium"], POWER_RANK["low"])


class RecordPowerTierTests(unittest.TestCase):
    def test_derives_from_record(self):
        rec = RegistryServerRecord(
            identity="x", name="X", description="a helper",
            tools=[ToolRecord(provider="r", server_id="x", name="deploy_service",
                              native_surface="r", description="")])
        self.assertEqual(record_power_tier(rec), "high")


if __name__ == "__main__":
    unittest.main()
