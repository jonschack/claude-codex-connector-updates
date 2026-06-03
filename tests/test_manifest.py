import json
import unittest

from mcp_newsletter.classifier import evidence_tier
from mcp_newsletter.manifest import (
    classify_manifest_record,
    declared_write_tools,
    manifest_urls,
    parse_readme_tools,
    parse_server_json_tools,
    raw_base,
    select_manifest_candidates,
)
from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_classify import classify_registry_record


class ServerJsonParseTests(unittest.TestCase):
    def test_parses_tools_array(self):
        text = json.dumps({"name": "io.x/y", "tools": [
            {"name": "create_issue", "description": "Create an issue"},
            {"name": "list_issues", "description": "List issues"}]})
        self.assertEqual(parse_server_json_tools(text),
                         [("create_issue", "Create an issue"),
                          ("list_issues", "List issues")])

    def test_no_tools_or_garbage_is_empty(self):
        self.assertEqual(parse_server_json_tools(json.dumps({"name": "x"})), [])
        self.assertEqual(parse_server_json_tools("not json"), [])
        self.assertEqual(parse_server_json_tools(""), [])


class ReadmeParseTests(unittest.TestCase):
    def test_parses_bullet_list_under_tools_heading(self):
        md = """# My MCP Server
Some intro prose mentioning send and create that must be ignored.

## Tools
- `send_message` — Send a message to a channel
- `get_history`: Read channel history

## Installation
- `npm install` something
"""
        tools = dict(parse_readme_tools(md))
        self.assertIn("send_message", tools)
        self.assertIn("get_history", tools)
        self.assertNotIn("npm", tools)  # Installation section not captured
        self.assertEqual(tools["send_message"], "Send a message to a channel")

    def test_parses_markdown_table(self):
        md = """## Available Tools
| Tool | Description |
| --- | --- |
| `deploy_app` | Deploy the application |
| `read_logs` | Read logs |
"""
        tools = dict(parse_readme_tools(md))
        self.assertEqual(set(tools), {"deploy_app", "read_logs"})

    def test_no_tools_section_returns_empty(self):
        self.assertEqual(parse_readme_tools("# Title\njust prose, `code`, no tools section"), [])


class DeclaredWriteToolsTests(unittest.TestCase):
    def test_keeps_only_write_tools_at_declared_manifest_tier(self):
        texts = {
            "server.json": json.dumps({"tools": [
                {"name": "create_issue", "description": "Create an issue"},
                {"name": "list_issues", "description": "List issues"}]}),
            "README": "## Tools\n- `send_message` — Send a message\n- `get_history`: Read history\n",
        }
        tools = declared_write_tools(texts)
        names = {t.name for t in tools}
        self.assertEqual(names, {"create_issue", "send_message"})
        for t in tools:
            self.assertEqual(t.write_confidence, "medium")
            self.assertEqual(evidence_tier(t.evidence), "declared_manifest")

    def test_dedupes_by_name_across_sources(self):
        texts = {
            "server.json": json.dumps({"tools": [{"name": "create_issue", "description": "Create"}]}),
            "README": "## Tools\n- `create_issue` — Create an issue (dup)\n",
        }
        self.assertEqual(len(declared_write_tools(texts)), 1)


class ClassifyManifestRecordTests(unittest.TestCase):
    def test_lifts_stdio_record_to_declared_manifest(self):
        rec = RegistryServerRecord(identity="repo:github.com/acme/x", name="X",
                                   repo_url="https://github.com/acme/x")
        texts = {"README": "## Tools\n- `send_message` — Send a message\n"}
        found = classify_manifest_record(rec, texts, run_date="2026-06-01")
        self.assertTrue(found)
        self.assertEqual(evidence_tier(rec.evidence), "declared_manifest")
        self.assertEqual(rec.confidence_by_source["manifest"]["confidence"], "medium")
        self.assertTrue(any(t.name == "send_message" for t in rec.tools))

    def test_declared_evidence_survives_classify_and_sets_confidence(self):
        rec = RegistryServerRecord(identity="repo:github.com/acme/x", name="X",
                                   repo_url="https://github.com/acme/x", description="")
        classify_manifest_record(rec, {"README": "## Tools\n- `delete_record` — Delete a record\n"},
                                 run_date="2026-06-01")
        classify_registry_record(rec, run_date="2026-06-01")
        self.assertEqual(evidence_tier(rec.evidence), "declared_manifest")
        self.assertIn(rec.write_confidence, {"medium", "high"})

    def test_no_write_tools_found_returns_false(self):
        rec = RegistryServerRecord(identity="r", name="X", repo_url="https://github.com/a/b")
        self.assertFalse(classify_manifest_record(rec, {"README": "## Tools\n- `list_x`: List\n"},
                                                  run_date="2026-06-01"))


class RawUrlTests(unittest.TestCase):
    def test_github_raw_base(self):
        self.assertEqual(raw_base("https://github.com/Acme/X.git"),
                         "https://raw.githubusercontent.com/Acme/X")

    def test_non_github_has_no_base(self):
        self.assertIsNone(raw_base("https://gitlab.com/a/b"))
        self.assertIsNone(raw_base(""))

    def test_manifest_urls_cover_three_files(self):
        urls = manifest_urls("https://github.com/a/b")
        self.assertEqual(set(urls), {"server.json", "package.json", "README"})


class SelectManifestCandidatesTests(unittest.TestCase):
    def _stdio(self, ident):
        return RegistryServerRecord(identity=ident, name=ident,
                                    repo_url=f"https://github.com/o/{ident}")

    def test_only_stdio_github_repos_with_no_remote(self):
        stdio = self._stdio("a")
        remote = RegistryServerRecord(identity="b", name="b",
                                      repo_url="https://github.com/o/b",
                                      remote_url="https://x/y")  # has endpoint -> discovery's job
        norepo = RegistryServerRecord(identity="c", name="c")
        gitlab = RegistryServerRecord(identity="d", name="d", repo_url="https://gitlab.com/o/d")
        sel = select_manifest_candidates([stdio, remote, norepo, gitlab], cap=10,
                                         last_parsed={}, cadence_days=3, run_date="2026-06-01")
        self.assertEqual([r.identity for r in sel], ["a"])

    def test_rotates_by_last_parsed_and_caps(self):
        recs = [self._stdio(x) for x in "abcde"]
        sel = select_manifest_candidates(recs, cap=2, last_parsed={"a": "2026-06-01"},
                                         cadence_days=3, run_date="2026-06-01")
        self.assertEqual(len(sel), 2)
        self.assertNotIn("a", [r.identity for r in sel])  # parsed today, within cadence


if __name__ == "__main__":
    unittest.main()
