import unittest
from unittest import mock

from mcp_newsletter.mcp_discovery import discover_remote_tools


class DiscoverySafetyTests(unittest.TestCase):
    def test_refuses_loopback_url_without_network(self):
        tools, result = discover_remote_tools("reg", "srv", "registry", "http://127.0.0.1/mcp")
        self.assertEqual(tools, [])
        self.assertFalse(result["ok"])
        self.assertIn("127.0.0.1", result["error"])

    def test_refuses_non_http_scheme(self):
        tools, result = discover_remote_tools("reg", "srv", "registry", "ftp://example.com/x")
        self.assertEqual(tools, [])
        self.assertFalse(result["ok"])

    def test_refuses_metadata_ip(self):
        tools, result = discover_remote_tools("reg", "srv", "registry", "http://169.254.169.254/")
        self.assertEqual(tools, [])
        self.assertFalse(result["ok"])

    def test_oversized_body_is_rejected(self):
        class FakeResp:
            headers = {}
            status = 200
            def read(self, n=-1):
                return b"x" * (n if n and n > 0 else 10_000_000)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        with mock.patch.dict("os.environ", {"MCP_NEWSLETTER_MAX_RESPONSE_BYTES": "100"}):
            with mock.patch("mcp_newsletter.mcp_discovery.urlopen", return_value=FakeResp()):
                tools, result = discover_remote_tools("reg", "srv", "registry", "https://8.8.8.8/mcp")
        self.assertEqual(tools, [])
        self.assertFalse(result["ok"])
        self.assertIn("exceeded", result["error"])


if __name__ == "__main__":
    unittest.main()
