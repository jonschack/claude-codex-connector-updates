import unittest

from mcp_newsletter.capability import (
    build_capability_feed,
    enrich_servers,
    evidence_tier,
    humanize_tool_name,
    summarize_tool,
)
from mcp_newsletter.models import ServerRecord, ToolRecord


def _tool(**kw):
    base = dict(provider="gemini", server_id="bt", name="create_instance", native_surface="connector")
    base.update(kw)
    return ToolRecord(**base)


class HumanizeTests(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(humanize_tool_name("create_instance"), "create instance")

    def test_camel_case(self):
        self.assertEqual(humanize_tool_name("createInstance"), "create instance")

    def test_dotted_namespace_uses_last_segment(self):
        self.assertEqual(humanize_tool_name("bigtable.create_table"), "create table")


class EvidenceTierTests(unittest.TestCase):
    def test_schema_is_verified_tools(self):
        self.assertEqual(evidence_tier(_tool(input_schema={"type": "object"})), "verified_tools")

    def test_annotation_only(self):
        self.assertEqual(evidence_tier(_tool(annotations={"readOnlyHint": False})), "annotation")

    def test_description_only(self):
        self.assertEqual(evidence_tier(_tool(description="Creates a thing.")), "claimed_description")

    def test_no_signal(self):
        self.assertEqual(evidence_tier(_tool()), "none")


class SummarizeToolTests(unittest.TestCase):
    def test_uses_first_sentence_and_example_prompt(self):
        out = summarize_tool(_tool(description="Create a new instance. Requires a project.", input_schema={"required": ["project_id"]}))
        self.assertEqual(out["summary"], "Create a new instance.")
        self.assertIn("create instance", out["example_prompt"].lower())
        self.assertEqual(out["evidence_tier"], "verified_tools")

    def test_falls_back_to_humanized_name_when_no_description(self):
        out = summarize_tool(_tool(name="list_tables"))
        self.assertIn("list tables", out["summary"].lower())
        self.assertIn("list tables", out["example_prompt"].lower())

    def test_injected_llm_overrides_text_but_keeps_tier(self):
        def fake_llm(tool):
            return {"summary": "Spin up a Bigtable instance", "example_prompt": '"Claude, stand up a 3-node Bigtable cluster"'}
        out = summarize_tool(_tool(input_schema={"x": 1}), llm=fake_llm)
        self.assertEqual(out["summary"], "Spin up a Bigtable instance")
        self.assertIn("Bigtable", out["example_prompt"])
        self.assertEqual(out["evidence_tier"], "verified_tools")

    def test_llm_failure_falls_back_to_deterministic(self):
        def boom(tool):
            raise RuntimeError("llm down")
        out = summarize_tool(_tool(description="Create a new instance."), llm=boom)
        self.assertEqual(out["summary"], "Create a new instance.")


class EnrichAndFeedTests(unittest.TestCase):
    def test_enrich_mutates_tools_and_feed_built(self):
        server = ServerRecord(
            provider="gemini", server_id="bt", native_surface="connector", name="Bigtable",
            tools=[_tool(description="Create a new instance.", input_schema={"required": ["project_id"]})],
        )
        n = enrich_servers([server])
        self.assertEqual(n, 1)
        tool = server.tools[0]
        self.assertTrue(tool.capability_summary)
        self.assertTrue(tool.example_prompt)
        self.assertEqual(tool.capability_tier, "verified_tools")

        feed = build_capability_feed([server])
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["server"], "Bigtable")
        self.assertEqual(feed[0]["tool"], "create_instance")
        self.assertEqual(feed[0]["evidence_tier"], "verified_tools")


if __name__ == "__main__":
    unittest.main()
