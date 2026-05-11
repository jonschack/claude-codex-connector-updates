import unittest

from mcp_newsletter.classifier import classify_server, classify_tool
from mcp_newsletter.models import ServerRecord, ToolRecord


class ClassifierTests(unittest.TestCase):
    def test_catalog_write_is_high_confidence(self):
        server = ServerRecord(
            provider="claude",
            server_id="linear",
            native_surface="connector",
            name="Linear",
            capabilities=["Read & write"],
        )
        confidence, evidence = classify_server(server)
        self.assertEqual(confidence, "high")
        self.assertTrue(evidence)

    def test_readonly_annotation_stays_low(self):
        tool = ToolRecord(
            provider="x",
            server_id="s",
            native_surface="connector",
            name="search_issues",
            description="Search issues",
            annotations={"readOnlyHint": True},
        )
        confidence, _ = classify_tool(tool)
        self.assertEqual(confidence, "low")

    def test_write_tool_text_is_medium(self):
        tool = ToolRecord(
            provider="x",
            server_id="s",
            native_surface="connector",
            name="create_issue",
            description="Create a new issue",
            input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
        )
        confidence, evidence = classify_tool(tool)
        self.assertEqual(confidence, "medium")
        self.assertTrue(evidence)

    def test_destructive_annotation_is_high(self):
        tool = ToolRecord(
            provider="x",
            server_id="s",
            native_surface="connector",
            name="delete_file",
            annotations={"destructiveHint": True},
        )
        confidence, _ = classify_tool(tool)
        self.assertEqual(confidence, "high")


if __name__ == "__main__":
    unittest.main()

