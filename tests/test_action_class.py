import unittest

from mcp_newsletter.action_class import (
    action_classes_for,
    coverage_by_action_class,
    record_action_classes,
)
from mcp_newsletter.models import ToolRecord
from mcp_newsletter.registries.base import RegistryServerRecord


class ActionClassesForTests(unittest.TestCase):
    def test_comms(self):
        self.assertIn("comms", action_classes_for("Send a Slack message"))

    def test_deploy(self):
        self.assertIn("deploy", action_classes_for("Deploy the app to production"))

    def test_money(self):
        self.assertIn("money", action_classes_for("Charge the customer's card"))

    def test_system_control(self):
        self.assertIn("system_control", action_classes_for("run a shell command"))

    def test_unmatched_is_other(self):
        self.assertEqual(action_classes_for("shows the weather forecast"), ["other"])


class RecordActionClassesTests(unittest.TestCase):
    def test_derives_from_description_tags_and_tool_names(self):
        rec = RegistryServerRecord(
            identity="x", name="X", description="A team helper",
            tags=["email"],
            tools=[ToolRecord(provider="registry", server_id="x", name="deploy_service",
                              native_surface="registry", description="")])
        classes = set(record_action_classes(rec))
        self.assertIn("comms", classes)   # from tag "email"
        self.assertIn("deploy", classes)  # from tool name


class CoverageByActionClassTests(unittest.TestCase):
    def _rec(self, ident, desc, kind):
        return RegistryServerRecord(identity=ident, name=ident, description=desc,
                                    write_confidence="medium",
                                    evidence=[{"kind": kind, "value": "x", "confidence": "medium"}])

    def test_tallies_per_class_by_evidence_tier(self):
        recs = {
            "a": self._rec("a", "send an email", "tool_text"),          # comms / verified
            "b": self._rec("b", "send a message", "registry_description"),  # comms / claimed
            "c": self._rec("c", "deploy the service", "declared_manifest"),  # deploy / declared
            "d": RegistryServerRecord(identity="d", name="d", description="reads weather"),  # no signal
        }
        cov = coverage_by_action_class(recs)
        self.assertEqual(cov["comms"]["verified_tools"], 1)
        self.assertEqual(cov["comms"]["claimed_description"], 1)
        self.assertEqual(cov["comms"]["total"], 2)
        self.assertEqual(cov["deploy"]["declared_manifest"], 1)
        self.assertNotIn("other", cov)  # the no-signal record is excluded entirely

    def test_empty_input(self):
        self.assertEqual(coverage_by_action_class({}), {})


if __name__ == "__main__":
    unittest.main()
