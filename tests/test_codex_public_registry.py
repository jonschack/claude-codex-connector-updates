import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.providers.codex import collect_codex

REGISTRY = json.dumps({
    "plugins": [
        {"name": "Aegis", "url": "https://github.com/x/aegis", "description": "planning, TDD", "category": "Dev"},
        {"name": "Agentizer", "url": "https://github.com/y/agentizer", "description": "agentfront", "category": "Tools"},
        {"name": "", "url": "https://github.com/z/none"},  # skipped (no name)
    ]
})


class CodexPublicRegistryTests(unittest.TestCase):
    def test_collects_public_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = CollectContext(root=Path(tmp), run_date="d", skip_network=False)
            env = {"MCP_NEWSLETTER_CODEX_PLUGIN_ROOT": str(Path(tmp) / "nonexistent")}
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(ctx, "fetch", side_effect=lambda p, u, l=None, **k: REGISTRY):
                servers = collect_codex(ctx)
        ids = sorted(s.server_id for s in servers)
        self.assertEqual(ids, ["aegis", "agentizer"])
        self.assertTrue(all(s.provider == "codex" for s in servers))
        self.assertTrue(all(s.native_surface == "plugin" for s in servers))


if __name__ == "__main__":
    unittest.main()
