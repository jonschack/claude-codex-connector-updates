# tests/test_registry_collectors.py
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.registries import apply_source_floor
from mcp_newsletter.registries.official import collect_official

FIX = Path(__file__).parent / "fixtures" / "registries"


def _ctx(tmp):
    return CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=False)


def _meta_ok():
    return {"status": 200, "content_type": "application/json", "error": ""}


class OfficialCollectorTests(unittest.TestCase):
    def test_parses_active_servers_and_skips_deleted(self):
        page = (FIX / "official_page1.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.official.fetch_text",
                            return_value=(page, _meta_ok())):
                entries = collect_official(ctx)
        names = {e.official_name for e in entries}
        self.assertIn("io.github.acme/slack", names)
        self.assertNotIn("io.github.acme/gone", names)  # status=deleted skipped
        slack = next(e for e in entries if e.official_name == "io.github.acme/slack")
        self.assertEqual(slack.remote_url, "https://mcp.acme.com/slack")
        self.assertEqual(slack.repo_url, "https://github.com/acme/slack")
        self.assertIn("messaging", slack.tags)

    def test_keeps_only_islatest_version(self):
        page = (FIX / "official_page1.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.official.fetch_text",
                            return_value=(page, _meta_ok())):
                entries = collect_official(ctx)
        multi = [e for e in entries if e.official_name == "io.github.acme/multi"]
        self.assertEqual(len(multi), 1)
        self.assertEqual(multi[0].description, "new desc")


class GithubServersCollectorTests(unittest.TestCase):
    def test_parses_github_repos_from_readme(self):
        readme = (FIX / "github_servers_readme.md").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.github_servers.fetch_text",
                            return_value=(readme, {"status": 200, "content_type": "text/plain", "error": ""})):
                from mcp_newsletter.registries.github_servers import collect_github_servers
                entries = collect_github_servers(ctx)
        repo_urls = {e.repo_url for e in entries}
        self.assertIn("https://github.com/acme/slack-mcp", repo_urls)
        self.assertIn("https://github.com/modelcontextprotocol/servers-filesystem", repo_urls)
        # all entries should have source = github_servers
        self.assertTrue(all(e.source == "github_servers" for e in entries))

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            from mcp_newsletter.registries.github_servers import collect_github_servers
            entries = collect_github_servers(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("skipped" in i.message for i in ctx.issues))


class DockerCollectorTests(unittest.TestCase):
    def test_parses_server_yaml_and_extracts_fields(self):
        listing = (FIX / "docker_listing.json").read_text()
        slack_yaml = (FIX / "docker_slack_server.yaml").read_text()
        # github dir returns empty yaml (no match) — use side_effect for sequential calls
        side_effects = [
            (listing, _meta_ok()),           # listing fetch
            (slack_yaml, _meta_ok()),         # slack/server.yaml
            ("name: github\n", _meta_ok()),   # github/server.yaml (minimal)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.docker.fetch_text",
                            side_effect=side_effects):
                from mcp_newsletter.registries.docker import collect_docker
                entries = collect_docker(ctx)
        names = {e.source_id for e in entries}
        self.assertIn("slack", names)
        slack = next(e for e in entries if e.source_id == "slack")
        self.assertEqual(slack.repo_url, "https://github.com/docker/mcp-slack")
        self.assertIn("messaging", slack.tags)

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            from mcp_newsletter.registries.docker import collect_docker
            entries = collect_docker(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("skip" in i.message.lower() for i in ctx.issues))


class PulsemcpCollectorTests(unittest.TestCase):
    def test_no_key_returns_empty_with_info_issue(self):
        """When MCP_NEWSLETTER_PULSEMCP_KEY is absent, returns [] and adds an info issue."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            env = {k: v for k, v in os.environ.items() if k != "MCP_NEWSLETTER_PULSEMCP_KEY"}
            with mock.patch.dict(os.environ, env, clear=True):
                from mcp_newsletter.registries.pulsemcp import collect_pulsemcp
                entries = collect_pulsemcp(ctx)
        self.assertEqual(entries, [])
        info_issues = [i for i in ctx.issues if i.severity == "info"]
        self.assertTrue(len(info_issues) >= 1)
        self.assertTrue(any("KEY" in i.message or "key" in i.message.lower() for i in info_issues))

    def test_parses_wrapped_servers_skips_deleted(self):
        """With a key set and the generic-registry-spec fixture, parses servers and skips deleted."""
        page = (FIX / "pulsemcp_page.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_PULSEMCP_KEY": "test-key"}):
                with mock.patch("mcp_newsletter.registries.pulsemcp._fetch_with_auth",
                                return_value=(page, _meta_ok())):
                    from mcp_newsletter.registries.pulsemcp import collect_pulsemcp
                    entries = collect_pulsemcp(ctx)
        # 3 servers in fixture, 1 deleted → 2 parsed
        self.assertEqual(len(entries), 2)
        slack = next(e for e in entries if "slack-mcp" in e.source_id)
        self.assertEqual(slack.repo_url, "https://github.com/acme/slack-mcp")
        self.assertEqual(slack.remote_url, "https://mcp.acme.com/slack")
        self.assertIn("messaging", slack.tags)
        self.assertEqual(slack.source, "pulsemcp")
        # deleted server must not appear
        self.assertFalse(any("gone" in e.source_id for e in entries))

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_PULSEMCP_KEY": "test-key"}):
                from mcp_newsletter.registries.pulsemcp import collect_pulsemcp
                entries = collect_pulsemcp(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("skip" in i.message.lower() for i in ctx.issues))


class GlamaCollectorTests(unittest.TestCase):
    def test_parses_servers_with_real_shape(self):
        page = (FIX / "glama_page.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.glama.fetch_text",
                            return_value=(page, _meta_ok())):
                from mcp_newsletter.registries.glama import collect_glama
                entries = collect_glama(ctx)
        self.assertEqual(len(entries), 2)
        # source_id is "{namespace}/{slug}"
        slack = next(e for e in entries if e.source_id == "acme/slack-mcp")
        self.assertEqual(slack.repo_url, "https://github.com/acme/slack-mcp")
        # attributes flat list becomes tags
        self.assertIn("hosting:cloud", slack.tags)
        self.assertEqual(slack.source, "glama")
        # tool names folded into description
        self.assertIn("create_message", slack.description)
        # no remote_url set (url field is a listing page, not MCP endpoint)
        self.assertEqual(slack.remote_url, "")

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            from mcp_newsletter.registries.glama import collect_glama
            entries = collect_glama(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("skip" in i.message.lower() for i in ctx.issues))


class SmitheryCollectorTests(unittest.TestCase):
    def test_no_key_returns_empty_with_info_issue(self):
        """When MCP_NEWSLETTER_SMITHERY_KEY is absent, returns [] and adds an info issue."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            # Ensure key is not set
            env = {k: v for k, v in os.environ.items() if k != "MCP_NEWSLETTER_SMITHERY_KEY"}
            with mock.patch.dict(os.environ, env, clear=True):
                from mcp_newsletter.registries.smithery import collect_smithery
                entries = collect_smithery(ctx)
        self.assertEqual(entries, [])
        info_issues = [i for i in ctx.issues if i.severity == "info"]
        self.assertTrue(len(info_issues) >= 1)
        self.assertTrue(any("KEY" in i.message or "key" in i.message.lower() for i in info_issues))

    def test_parses_servers_when_key_is_set(self):
        page = (FIX / "smithery_page.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_SMITHERY_KEY": "test-key"}):
                with mock.patch("mcp_newsletter.registries.smithery._fetch_with_auth",
                                return_value=(page, _meta_ok())):
                    from mcp_newsletter.registries.smithery import collect_smithery
                    entries = collect_smithery(ctx)
        self.assertEqual(len(entries), 2)
        slack = next(e for e in entries if "slack" in e.source_id)
        self.assertEqual(slack.repo_url, "https://github.com/acme/slack-mcp")
        self.assertIn("messaging", slack.tags)
        self.assertEqual(slack.source, "smithery")

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_SMITHERY_KEY": "test-key"}):
                from mcp_newsletter.registries.smithery import collect_smithery
                entries = collect_smithery(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("skip" in i.message.lower() for i in ctx.issues))


class McpsoCollectorTests(unittest.TestCase):
    def test_parses_github_repos_from_html(self):
        html = (FIX / "mcpso_listing.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.mcpso.fetch_text",
                            return_value=(html, {"status": 200, "content_type": "text/html", "error": ""})):
                from mcp_newsletter.registries.mcpso import collect_mcpso
                entries = collect_mcpso(ctx)
        repo_urls = {e.repo_url for e in entries}
        self.assertIn("https://github.com/acme/slack-mcp", repo_urls)
        self.assertIn("https://github.com/community/weather-mcp", repo_urls)
        self.assertTrue(all(e.source == "mcpso" for e in entries))

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            from mcp_newsletter.registries.mcpso import collect_mcpso
            entries = collect_mcpso(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("skipped" in i.message for i in ctx.issues))


class FloorTests(unittest.TestCase):
    def test_known_large_source_returning_zero_is_marked_failed(self):
        ok = {"official": True}
        counts = {"official": 0}
        apply_source_floor(ok, counts, history={"official": 1400}, first_run=False)
        self.assertFalse(ok["official"])  # frozen: parser likely broke

    def test_legitimately_small_source_not_demoted(self):
        ok = {"docker": True}
        counts = {"docker": 180}
        apply_source_floor(ok, counts, history={"docker": 200}, first_run=False)
        self.assertTrue(ok["docker"])

    def test_first_run_uses_absolute_minimum(self):
        ok = {"official": True}
        apply_source_floor(ok, {"official": 0}, history={}, first_run=True)
        self.assertFalse(ok["official"])  # below built-in absolute floor


if __name__ == "__main__":
    unittest.main()
