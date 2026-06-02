"""Live contract tests — hit real sources and assert they still return data.

These are the freshness guard the offline fixture tests structurally cannot be:
a fixture test passes even when the live site's DOM/endpoint has drifted. Skipped
unless MCP_NEWSLETTER_LIVE_TESTS=1 (so the normal offline suite stays green and
fast); run on a schedule in CI with continue-on-error so drift is visible without
blocking PRs.
"""

import os
import tempfile
import unittest
from pathlib import Path

from mcp_newsletter.context import CollectContext
from mcp_newsletter.health import REGISTRY_FLOORS, VENDOR_FLOORS

LIVE = os.environ.get("MCP_NEWSLETTER_LIVE_TESTS") == "1"


@unittest.skipUnless(LIVE, "live contract tests; set MCP_NEWSLETTER_LIVE_TESTS=1 to run")
class VendorContractTests(unittest.TestCase):
    def _ctx(self) -> CollectContext:
        tmp = tempfile.mkdtemp()
        return CollectContext(root=Path(tmp), run_date="live", skip_network=False)

    def _assert_floor(self, name: str, count: int) -> None:
        floor = VENDOR_FLOORS.get(name, 1)
        self.assertGreaterEqual(
            count, floor,
            f"{name} collected {count} < floor {floor} — collector likely stale (DOM/endpoint drift)",
        )

    def test_claude(self):
        from mcp_newsletter.providers.claude import collect_claude
        self._assert_floor("claude", len(collect_claude(self._ctx())))

    def test_cline(self):
        from mcp_newsletter.providers.cline import collect_cline
        self._assert_floor("cline", len(collect_cline(self._ctx())))

    def test_cloudflare(self):
        from mcp_newsletter.providers.cloudflare import collect_cloudflare
        self._assert_floor("cloudflare", len(collect_cloudflare(self._ctx())))

    def test_gemini(self):
        from mcp_newsletter.providers.gemini import collect_gemini
        self._assert_floor("gemini", len(collect_gemini(self._ctx())))

    # Phase 1b: add test_openai / test_cursor / test_vscode / test_continue /
    # test_codex once those collectors are repaired against their live sources.


@unittest.skipUnless(LIVE, "live contract tests; set MCP_NEWSLETTER_LIVE_TESTS=1 to run")
class RegistryContractTests(unittest.TestCase):
    def test_enabled_registries_meet_half_floor(self):
        from mcp_newsletter.registries import collect_all_registries
        tmp = tempfile.mkdtemp()
        ctx = CollectContext(root=Path(tmp), run_date="live", skip_network=False)
        collection = collect_all_registries(ctx)
        for source, floor in REGISTRY_FLOORS.items():
            count = collection.counts.get(source)
            if count is None:
                continue  # source disabled this run
            self.assertGreaterEqual(
                count, floor // 2,
                f"{source} collected {count} — well below floor {floor} (source may be broken)",
            )


if __name__ == "__main__":
    unittest.main()
