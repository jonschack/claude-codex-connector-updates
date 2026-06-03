import unittest

from mcp_newsletter.action_power import (
    POWER_RANK,
    power_tier_for,
    record_power,
    record_power_tier,
    tool_power,
)
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


class ToolPowerTests(unittest.TestCase):
    def test_keyword_only_is_low_confidence(self):
        t = ToolRecord(provider="r", server_id="x", name="send_message",
                       native_surface="r", description="Send a message")
        tier, conf = tool_power(t)
        self.assertEqual(tier, "high")     # comms
        self.assertEqual(conf, "low")      # keyword-only (no schema/annotations)

    def test_schema_or_annotations_raise_confidence(self):
        t = ToolRecord(provider="r", server_id="x", name="send_message",
                       native_surface="r", description="Send a message",
                       input_schema={"type": "object", "properties": {"to": {}}})
        _, conf = tool_power(t)
        self.assertEqual(conf, "high")     # schema-derived

    def test_destructive_open_world_bumps_within_tier(self):
        # a data_write tool (medium) with destructive+openWorld bumps to high
        t = ToolRecord(provider="r", server_id="x", name="update_row",
                       native_surface="r", description="Update a database row",
                       annotations={"destructiveHint": True, "openWorldHint": True})
        tier, conf = tool_power(t)
        self.assertEqual(tier, "high")
        self.assertEqual(conf, "high")     # annotation-derived

    def test_no_signal_is_low(self):
        t = ToolRecord(provider="r", server_id="x", name="thing",
                       native_surface="r", description="does a thing")
        tier, _ = tool_power(t)
        self.assertEqual(tier, "low")


class RecordPowerTests(unittest.TestCase):
    def test_max_over_verified_tools_with_confidence(self):
        rec = RegistryServerRecord(
            identity="x", name="X", description="a helper",
            tools=[
                ToolRecord(provider="r", server_id="x", name="list_things",
                           native_surface="r", description="List",
                           input_schema={"type": "object"}),
                ToolRecord(provider="r", server_id="x", name="charge_card",
                           native_surface="r", description="Charge a card",
                           input_schema={"type": "object"}),
            ])
        tier, conf = record_power(rec)
        self.assertEqual(tier, "high")     # max over tools (charge -> money -> high)
        self.assertEqual(conf, "high")     # schema-derived

    def test_falls_back_to_keyword_when_no_tools(self):
        rec = RegistryServerRecord(identity="x", name="X", description="deploy the app")
        tier, conf = record_power(rec)
        self.assertEqual(tier, "high")     # keyword deploy
        self.assertEqual(conf, "low")      # no tools -> keyword-only


if __name__ == "__main__":
    unittest.main()
