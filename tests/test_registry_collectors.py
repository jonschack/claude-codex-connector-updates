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

    def test_parses_live_readme_fixture(self):
        """Verifies parser against captured live README from modelcontextprotocol/servers (2026-05-31).
        The README now links primarily to SDK repos and a few archived/community servers.
        extract_github_repos correctly extracts all github.com links it can find.
        """
        readme = (FIX / "github_servers_live.md").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.github_servers.fetch_text",
                            return_value=(readme, {"status": 200, "content_type": "text/plain", "error": ""})):
                from mcp_newsletter.registries.github_servers import collect_github_servers
                entries = collect_github_servers(ctx)
        repo_urls = {e.repo_url for e in entries}
        # SDK repos and community server links both extracted
        self.assertIn("https://github.com/modelcontextprotocol/typescript-sdk", repo_urls)
        self.assertIn("https://github.com/zencoderai/slack-mcp-server", repo_urls)
        self.assertIn("https://github.com/brave/brave-search-mcp-server", repo_urls)
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
        """Fixture uses real docker/mcp-registry server.yaml shape (verified 2026-05-31).
        Fields: about.description, source.project, remote.url, meta.category, meta.tags[].
        """
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
        self.assertIn("Send and receive Slack messages", slack.description)

    def test_parses_live_fixture_shapes(self):
        """Verifies parser against captured live fixtures from docker/mcp-registry (2026-05-31).
        Covers: local server (source.project), remote server (remote.url), meta.tags list.
        """
        listing = (FIX / "docker_live_listing.json").read_text()
        sqlite_yaml = (FIX / "docker_live_sqlite_server.yaml").read_text()
        airtable_yaml = (FIX / "docker_live_airtable_server.yaml").read_text()
        ais_yaml = (FIX / "docker_live_ais_fleet_server.yaml").read_text()
        side_effects = [
            (listing, _meta_ok()),
            (sqlite_yaml, _meta_ok()),
            (airtable_yaml, _meta_ok()),
            (ais_yaml, _meta_ok()),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.docker.fetch_text",
                            side_effect=side_effects):
                from mcp_newsletter.registries.docker import collect_docker
                entries = collect_docker(ctx)
        source_ids = {e.source_id for e in entries}
        self.assertIn("SQLite", source_ids)
        self.assertIn("airtable-mcp-server", source_ids)
        self.assertIn("ais-fleet", source_ids)

        sqlite = next(e for e in entries if e.source_id == "SQLite")
        self.assertEqual(sqlite.repo_url, "https://github.com/modelcontextprotocol/servers")
        self.assertIn("database", sqlite.tags)
        self.assertIn("Database interaction", sqlite.description)

        airtable = next(e for e in entries if e.source_id == "airtable-mcp-server")
        self.assertEqual(airtable.repo_url, "https://github.com/domdomegg/airtable-mcp-server")
        self.assertIn("productivity", airtable.tags)

        ais = next(e for e in entries if e.source_id == "ais-fleet")
        self.assertEqual(ais.remote_url, "https://mcp.aisfleet.com/sse")
        self.assertEqual(ais.repo_url, "")
        self.assertIn("boating", ais.tags)

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

    def test_with_key_parses_inline_page(self):
        """With key set and inline synthetic page, parses io.pm/sender and skips io.pm/gone (deleted)."""
        PAGE = json.dumps({
            "servers": [
                {"server": {"name": "io.pm/sender", "description": "Send things",
                            "repository": {"url": "https://github.com/pm/sender"},
                            "remotes": [{"type": "streamable-http", "url": "https://mcp.pm/sender"}]},
                 "_meta": {"com.pulsemcp.registry/official": {"status": "active"}}},
                {"server": {"name": "io.pm/gone", "description": "x"},
                 "_meta": {"com.pulsemcp.registry/official": {"status": "deleted"}}}
            ],
            "metadata": {"nextCursor": None}
        })
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_PULSEMCP_KEY": "test"}):
                with mock.patch("mcp_newsletter.registries.pulsemcp._fetch_with_auth",
                                return_value=(PAGE, {"status": 200, "content_type": "application/json", "error": ""})):
                    from mcp_newsletter.registries.pulsemcp import collect_pulsemcp
                    entries = collect_pulsemcp(ctx)
        # io.pm/sender should be present; io.pm/gone must be skipped (status=deleted)
        self.assertEqual(len(entries), 1)
        sender = entries[0]
        self.assertEqual(sender.official_name, "io.pm/sender")
        self.assertEqual(sender.repo_url, "https://github.com/pm/sender")
        self.assertEqual(sender.remote_url, "https://mcp.pm/sender")
        self.assertFalse(any(e.official_name == "io.pm/gone" for e in entries))

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

    def test_detail_cap_zero_does_not_fetch_detail(self):
        """Default cap=0: only the single list fetch occurs; no detail URL is called."""
        page = (FIX / "glama_page.json").read_text()
        mock_fetch = mock.Mock(return_value=(page, _meta_ok()))
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_GLAMA_DETAIL_CAP": "0"}):
                with mock.patch("mcp_newsletter.registries.glama.fetch_text", mock_fetch):
                    from mcp_newsletter.registries.glama import collect_glama
                    entries = collect_glama(ctx)
        # fetch_text called exactly once (the list page)
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(len(entries), 2)

    def test_detail_cap_nonzero_folds_tool_names_from_detail(self):
        """cap=5: write-candidate entry with empty tools gets detail fetch; tool names folded in."""
        page = (FIX / "glama_page.json").read_text()
        detail = (FIX / "glama_detail.json").read_text()
        # side_effect: first call = list page; subsequent calls = detail responses
        side_effects = [
            (page, _meta_ok()),    # list page
            (detail, _meta_ok()),  # detail for acme/github-mcp (write-candidate, no tools yet)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_GLAMA_DETAIL_CAP": "5"}):
                with mock.patch("mcp_newsletter.registries.glama.fetch_text",
                                side_effect=side_effects):
                    from mcp_newsletter.registries.glama import collect_glama
                    entries = collect_glama(ctx)
        github = next(e for e in entries if e.source_id == "acme/github-mcp")
        # Tool names from the detail fixture should be folded into the description
        self.assertIn("create_issue", github.description)
        self.assertIn("Tools:", github.description)
        # Slack entry (already has tools from list) should be unchanged
        slack = next(e for e in entries if e.source_id == "acme/slack-mcp")
        self.assertIn("create_message", slack.description)

    def test_detail_cap_nonzero_skip_network_no_detail_fetch(self):
        """cap=5 but skip_network=True: detail fetch is skipped entirely."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            mock_fetch = mock.Mock(return_value=("", {"error": "skipped"}))
            with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_GLAMA_DETAIL_CAP": "5"}):
                with mock.patch("mcp_newsletter.registries.glama.fetch_text", mock_fetch):
                    from mcp_newsletter.registries.glama import collect_glama
                    entries = collect_glama(ctx)
        # skip_network exits before any fetch; detail fetch also never happens
        self.assertEqual(entries, [])
        mock_fetch.assert_not_called()


class SmitheryCollectorTests(unittest.TestCase):
    def test_no_key_still_parses_public_page(self):
        """Public endpoint — no key required. Without a key, servers are still parsed."""
        page = (FIX / "smithery_public.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            env = {k: v for k, v in os.environ.items() if k != "MCP_NEWSLETTER_SMITHERY_KEY"}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("mcp_newsletter.registries.smithery._fetch",
                                return_value=(page, _meta_ok())):
                    from mcp_newsletter.registries.smithery import collect_smithery
                    entries = collect_smithery(ctx)
        self.assertGreaterEqual(len(entries), 2)
        # source_id == qualifiedName
        source_ids = {e.source_id for e in entries}
        self.assertIn("gmail", source_ids)
        # name mapped from displayName
        gmail = next(e for e in entries if e.source_id == "gmail")
        self.assertEqual(gmail.name, "Gmail MCP")
        # description mapped
        self.assertIn("Gmail", gmail.description)
        # source = smithery
        self.assertTrue(all(e.source == "smithery" for e in entries))
        # no issues raised (public, no key needed)
        self.assertEqual(ctx.issues, [])

    def test_pagination_stops_at_total_pages(self):
        """Single-page fixture (totalPages=1) triggers exactly one fetch."""
        page = (FIX / "smithery_public.json").read_text()
        mock_fetch = mock.Mock(return_value=(page, _meta_ok()))
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            env = {k: v for k, v in os.environ.items() if k != "MCP_NEWSLETTER_SMITHERY_KEY"}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("mcp_newsletter.registries.smithery._fetch", mock_fetch):
                    from mcp_newsletter.registries.smithery import collect_smithery
                    entries = collect_smithery(ctx)
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertGreaterEqual(len(entries), 2)

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            from mcp_newsletter.registries.smithery import collect_smithery
            entries = collect_smithery(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("skip" in i.message.lower() for i in ctx.issues))

    def test_invalid_json_returns_empty_with_issue(self):
        """Malformed JSON body → [] and an issue, no exception raised."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.smithery._fetch",
                            return_value=("not-json{{{", _meta_ok())):
                from mcp_newsletter.registries.smithery import collect_smithery
                entries = collect_smithery(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("json" in i.message.lower() or "JSON" in i.message for i in ctx.issues))


class McpsoCollectorTests(unittest.TestCase):
    def test_parses_rsc_payload_servers(self):
        """Parses ≥2 servers from the RSC fixture; checks repo_url, tags, source."""
        html = (FIX / "mcpso_rsc.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.mcpso.fetch_text",
                            return_value=(html, {"status": 200, "content_type": "text/html", "error": ""})):
                from mcp_newsletter.registries.mcpso import collect_mcpso
                entries = collect_mcpso(ctx)
        self.assertGreaterEqual(len(entries), 2)
        self.assertTrue(all(e.source == "mcpso" for e in entries))
        # repo_url should be the GitHub URL from the 'url' field
        repo_urls = {e.repo_url for e in entries}
        self.assertIn("https://github.com/TencentEdgeOne/edgeone-pages-mcp", repo_urls)
        self.assertIn("https://github.com/modelcontextprotocol/servers", repo_urls)

    def test_inline_tools_folded_into_description(self):
        """A server with an inline tools list has tool names appended to its description."""
        html = (FIX / "mcpso_rsc.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.mcpso.fetch_text",
                            return_value=(html, {"status": 200, "content_type": "text/html", "error": ""})):
                from mcp_newsletter.registries.mcpso import collect_mcpso
                entries = collect_mcpso(ctx)
        edgeone = next(
            (e for e in entries if e.repo_url == "https://github.com/TencentEdgeOne/edgeone-pages-mcp"),
            None,
        )
        self.assertIsNotNone(edgeone)
        self.assertIn("deploy-html", edgeone.description)
        self.assertIn("Tools:", edgeone.description)

    def test_i18n_label_objects_without_uuid_excluded(self):
        """Objects that lack a real uuid (e.g. i18n label dictionaries) are not returned."""
        html = (FIX / "mcpso_rsc.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.mcpso.fetch_text",
                            return_value=(html, {"status": 200, "content_type": "text/html", "error": ""})):
                from mcp_newsletter.registries.mcpso import collect_mcpso
                entries = collect_mcpso(ctx)
        # The fixture contains an i18n fragment ({"i18n": {...}}) with no uuid.
        # It must not produce any entry.  Total should be exactly 2 (the two server objects).
        self.assertEqual(len(entries), 2)
        for e in entries:
            # Every source_id must look like a real UUID (contains '-') or a valid server name
            self.assertTrue(
                e.source_id and "i18n" not in e.source_id,
                f"Unexpected source_id: {e.source_id!r}",
            )

    def test_brace_in_description_not_dropped(self):
        """A server whose description contains literal } characters must not be silently dropped.

        The old brace-counting walk would mis-count the } inside \"Returns JSON like {} on success\"
        and either overshoot the object boundary or produce a json.loads failure, causing the
        server to vanish.  raw_decode respects quoted strings, so it must survive.
        """
        html = (FIX / "mcpso_brace_rsc.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.mcpso.fetch_text",
                            return_value=(html, {"status": 200, "content_type": "text/html", "error": ""})):
                from mcp_newsletter.registries.mcpso import collect_mcpso
                entries = collect_mcpso(ctx)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.source_id, "brace-test-uuid-0000-0000-000000000001")
        self.assertEqual(e.repo_url, "https://github.com/example/brace-server")
        self.assertIn("{}", e.description)  # brace pair preserved verbatim in description

    def test_skip_network_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=True)
            from mcp_newsletter.registries.mcpso import collect_mcpso
            entries = collect_mcpso(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(any("skipped" in i.message for i in ctx.issues))

    def test_empty_markup_or_no_rsc_servers_adds_issue(self):
        """When markup is present but contains no RSC server objects, a parser-break issue is added."""
        bare_html = "<html><body><p>No RSC payload here.</p></body></html>"
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.mcpso.fetch_text",
                            return_value=(bare_html, {"status": 200, "content_type": "text/html", "error": ""})):
                from mcp_newsletter.registries.mcpso import collect_mcpso
                entries = collect_mcpso(ctx)
        self.assertEqual(entries, [])
        self.assertTrue(
            any("no servers parsed" in i.message.lower() or "rsc" in i.message.lower()
                for i in ctx.issues),
            f"Expected parser-break issue, got: {[i.message for i in ctx.issues]}",
        )


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
