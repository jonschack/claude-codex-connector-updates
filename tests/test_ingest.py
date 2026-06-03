import json
import unittest

from mcp_newsletter.ingest.github_watch import (
    GITHUB_GRAPHQL_BATCH,
    build_graphql_query,
    momentum,
    parse_graphql,
)
from mcp_newsletter.ingest.official_incremental import parse_incremental
from mcp_newsletter.ingest.package_watch import parse_npm_search, parse_pypi_rss


class OfficialIncrementalTests(unittest.TestCase):
    def test_parses_entries_cursor_and_tombstones(self):
        payload = {
            "servers": [
                {"server": {"name": "io.x/new", "description": "Send things",
                            "repository": {"url": "https://github.com/x/new"},
                            "remotes": [{"url": "https://mcp.x/new"}]},
                 "_meta": {"io.modelcontextprotocol.registry/official":
                           {"updatedAt": "2026-06-02", "status": "active"}}},
                {"server": {"name": "io.x/gone"},
                 "_meta": {"io.modelcontextprotocol.registry/official":
                           {"status": "deleted"}}},
            ],
            "metadata": {"nextCursor": "abc123"},
        }
        entries, cursor, deleted = parse_incremental(json.dumps(payload))
        self.assertEqual([e.official_name for e in entries], ["io.x/new"])
        self.assertEqual(entries[0].remote_url, "https://mcp.x/new")
        self.assertEqual(cursor, "abc123")
        self.assertEqual(deleted, ["io.x/gone"])

    def test_garbage_is_empty(self):
        self.assertEqual(parse_incremental("not json"), ([], "", []))


class NpmSearchTests(unittest.TestCase):
    def test_filters_to_mcp_and_extracts_repo(self):
        payload = {"objects": [
            {"package": {"name": "cool-mcp-server", "description": "An MCP server",
                         "keywords": ["mcp"], "date": "2026-06-01",
                         "links": {"repository": "https://github.com/a/cool-mcp-server"}}},
            {"package": {"name": "unrelated-lib", "description": "left-pad",
                         "keywords": ["string"]}},
        ]}
        out = parse_npm_search(json.dumps(payload))
        self.assertEqual([e.name for e in out], ["cool-mcp-server"])
        self.assertEqual(out[0].source, "npm")
        self.assertEqual(out[0].repo_url, "https://github.com/a/cool-mcp-server")

    def test_garbage_is_empty(self):
        self.assertEqual(parse_npm_search("x"), [])


class PypiRssTests(unittest.TestCase):
    def test_filters_to_mcp_packages(self):
        xml = """<rss><channel>
          <item><title>mcp-weather 0.1.0</title><link>https://pypi.org/project/mcp-weather/</link>
                <description>A weather MCP server</description><pubDate>Mon, 01 Jun 2026</pubDate></item>
          <item><title>numpy 2.0</title><link>https://pypi.org/project/numpy/</link>
                <description>arrays</description></item>
        </channel></rss>"""
        out = parse_pypi_rss(xml)
        self.assertEqual([e.name for e in out], ["mcp-weather"])
        self.assertEqual(out[0].source, "pypi")


class GithubWatchTests(unittest.TestCase):
    def test_query_batches_and_aliases(self):
        q = build_graphql_query([("acme", "x"), ("acme", "y")])
        self.assertIn("r0: repository(owner: \"acme\", name: \"x\")", q)
        self.assertIn("r1: repository(owner: \"acme\", name: \"y\")", q)
        self.assertIn("stargazerCount", q)

    def test_query_caps_at_batch_size(self):
        repos = [("o", f"r{i}") for i in range(GITHUB_GRAPHQL_BATCH + 50)]
        q = build_graphql_query(repos)
        self.assertIn(f"r{GITHUB_GRAPHQL_BATCH - 1}:", q)
        self.assertNotIn(f"r{GITHUB_GRAPHQL_BATCH}:", q)

    def test_parse_skips_null_repos(self):
        payload = {"data": {
            "r0": {"nameWithOwner": "acme/x", "stargazerCount": 1200,
                   "releases": {"nodes": [{"tagName": "v2.0", "createdAt": "2026-06-01"}]}},
            "r1": None,  # deleted/inaccessible
        }}
        out = parse_graphql(json.dumps(payload))
        self.assertEqual(set(out), {"acme/x"})
        self.assertEqual(out["acme/x"]["stars"], 1200)
        self.assertEqual(out["acme/x"]["latest_release"], "v2.0")

    def test_momentum_deltas(self):
        prev = {"acme/x": {"stars": 1000, "latest_release": "v1.0"}}
        cur = {
            "acme/x": {"stars": 1200, "latest_release": "v2.0"},   # +200, new release
            "acme/new": {"stars": 50, "latest_release": "v1.0"},   # first sighting
        }
        m = momentum(prev, cur)
        self.assertEqual(m["acme/x"]["star_delta"], 200)
        self.assertTrue(m["acme/x"]["new_release"])
        self.assertEqual(m["acme/new"]["star_delta"], 0)       # no false spike
        self.assertFalse(m["acme/new"]["new_release"])         # no baseline

    def test_parse_garbage_is_empty(self):
        self.assertEqual(parse_graphql("x"), {})


class _FakeCtx:
    """Minimal ctx returning canned bodies keyed by fetch label."""
    def __init__(self, bodies, skip_network=False):
        self.bodies = bodies
        self.skip_network = skip_network
    def fetch(self, provider, url, label=None, extra_headers=None):
        return self.bodies.get(label)


class _FakeMeta:
    def __init__(self):
        self.official_cursor = ""
        self.first_seen = {}
        self.github_snapshot = {}


class AugmentCatchNewTests(unittest.TestCase):
    def test_additive_merge_new_identities_and_tombstone(self):
        import os
        from unittest import mock
        from mcp_newsletter.ingest.catch_new import augment_catch_new
        from mcp_newsletter.identity import canonical_key
        from mcp_newsletter.registries.base import RegistryServerRecord

        # an existing record that the incremental tombstone should delete
        gone_id = canonical_key(official_name="io.x/gone")
        current = {gone_id: RegistryServerRecord(identity=gone_id, name="gone")}

        incremental = json.dumps({"servers": [
            {"server": {"name": "io.x/fresh", "description": "Send things",
                        "repository": {"url": "https://github.com/x/fresh"}},
             "_meta": {"io.modelcontextprotocol.registry/official":
                       {"updatedAt": "2026-06-02", "status": "active"}}},
            {"server": {"name": "io.x/gone"},
             "_meta": {"io.modelcontextprotocol.registry/official": {"status": "deleted"}}},
        ], "metadata": {"nextCursor": ""}})

        ctx = _FakeCtx({"official-incremental-0": incremental})
        meta = _FakeMeta()
        with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_OFFICIAL_INCREMENTAL": "1",
                                          "MCP_NEWSLETTER_PACKAGE_WATCH": "0"}):
            new_ids = augment_catch_new(ctx, current, meta, "2026-06-02")

        fresh_id = canonical_key(official_name="io.x/fresh")
        self.assertIn(fresh_id, new_ids)            # surfaced as new
        self.assertIn(fresh_id, current)            # additively merged in
        self.assertNotIn(gone_id, current)          # tombstone removed it
        self.assertEqual(meta.official_cursor, "2026-06-02")   # cursor advanced
        self.assertEqual(meta.first_seen[fresh_id], "2026-06-02")  # stamped new

    def test_skip_network_is_noop(self):
        from mcp_newsletter.ingest.catch_new import augment_catch_new
        ctx = _FakeCtx({}, skip_network=True)
        self.assertEqual(augment_catch_new(ctx, {}, _FakeMeta(), "2026-06-02"), set())


class GithubMomentumWiringTests(unittest.TestCase):
    def test_candidate_only_momentum_threaded(self):
        import os
        from unittest import mock
        from mcp_newsletter.ingest import catch_new
        from mcp_newsletter.registries.base import RegistryServerRecord

        cand = RegistryServerRecord(identity="repo:github.com/acme/x", name="X",
                                    repo_url="https://github.com/acme/x")
        meta = _FakeMeta()
        meta.github_snapshot = {"acme/x": {"stars": 1000, "latest_release": "v1"}}
        graphql = json.dumps({"data": {"r0": {
            "nameWithOwner": "acme/x", "stargazerCount": 1300,
            "releases": {"nodes": [{"tagName": "v2", "createdAt": "2026-06-01"}]}}}})

        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}), \
             mock.patch.object(catch_new, "_github_post", return_value=graphql):
            out = catch_new.github_momentum_for_candidates([cand], meta)
        self.assertIn("repo:github.com/acme/x", out)
        self.assertGreater(out["repo:github.com/acme/x"], 0)   # +300 stars -> momentum
        self.assertEqual(meta.github_snapshot["acme/x"]["stars"], 1300)  # snapshot updated

    def test_new_release_not_stuck_true_across_runs(self):
        import os
        from unittest import mock
        from mcp_newsletter.ingest import catch_new
        from mcp_newsletter.registries.base import RegistryServerRecord

        cand = RegistryServerRecord(identity="repo:github.com/acme/x", name="X",
                                    repo_url="https://github.com/acme/x")
        meta = _FakeMeta()
        # same release tag as the persisted snapshot, no star change -> no momentum
        meta.github_snapshot = {"acme/x": {"stars": 1300, "latest_release": "v2"}}
        graphql = json.dumps({"data": {"r0": {
            "nameWithOwner": "acme/x", "stargazerCount": 1300,
            "releases": {"nodes": [{"tagName": "v2", "createdAt": "2026-06-01"}]}}}})
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}), \
             mock.patch.object(catch_new, "_github_post", return_value=graphql):
            out = catch_new.github_momentum_for_candidates([cand], meta)
        self.assertEqual(out, {})  # release unchanged + no stars -> new_release False

    def test_no_token_is_noop(self):
        import os
        from unittest import mock
        from mcp_newsletter.ingest import catch_new
        from mcp_newsletter.registries.base import RegistryServerRecord
        cand = RegistryServerRecord(identity="x", name="x", repo_url="https://github.com/a/b")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            self.assertEqual(catch_new.github_momentum_for_candidates([cand], _FakeMeta()), {})


if __name__ == "__main__":
    unittest.main()
