import unittest
from mcp_newsletter.landscape_ingest import normalize_vendor_record


class NormalizeVendorTests(unittest.TestCase):
    def test_maps_vendor_record_to_landscape_shape(self):
        v = {
            "provider": "claude", "server_id": "linear", "name": "Linear",
            "description": "Create and update issues", "capabilities": ["Read & write"],
            "write_confidence": "high", "evidence": [{"kind": "catalog_capability", "value": ["Read & write"], "confidence": "high"}],
            "remote_url": "https://mcp.linear.app/sse",
            "source_urls": ["https://github.com/linear/mcp", "https://linear.app"],
            "native_surface": "connector", "transport": "mcp", "metadata": {},
        }
        out = normalize_vendor_record(v, run_date="2026-05-31")
        self.assertEqual(out["identity"], "claude:linear")
        self.assertEqual(out["sources"], [{"source": "claude"}])
        self.assertEqual(out["remote_url"], "https://mcp.linear.app/sse")
        self.assertEqual(out["repo_url"], "https://github.com/linear/mcp")
        self.assertEqual(out["tags"], ["Read & write"])
        self.assertEqual(out["write_confidence"], "high")
        self.assertEqual(out["confidence_by_source"]["catalog"]["confidence"], "high")

    def test_no_github_source_url_leaves_repo_empty(self):
        v = {"provider": "grok", "server_id": "gmail", "name": "Gmail", "description": "",
             "capabilities": [], "write_confidence": "unknown", "evidence": [],
             "remote_url": "", "source_urls": ["https://x.ai/docs"], "native_surface": "connector",
             "transport": "catalog", "metadata": {}}
        out = normalize_vendor_record(v, run_date="2026-05-31")
        self.assertEqual(out["repo_url"], "")
        self.assertEqual(out["confidence_by_source"], {})


if __name__ == "__main__":
    unittest.main()
