from __future__ import annotations

import io
import os
import unittest
from unittest import mock

from mcp_newsletter.netguard import is_safe_url


class IsSafeUrlTests(unittest.TestCase):
    def test_public_ip_literal_is_allowed(self):
        ok, reason = is_safe_url("https://8.8.8.8/mcp")
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "")

    def test_loopback_is_blocked(self):
        ok, reason = is_safe_url("http://127.0.0.1:8080/mcp")
        self.assertFalse(ok)
        self.assertIn("127.0.0.1", reason)

    def test_ipv6_loopback_is_blocked(self):
        ok, reason = is_safe_url("http://[::1]/mcp")
        self.assertFalse(ok)

    def test_private_range_is_blocked(self):
        ok, _ = is_safe_url("http://10.0.0.5/mcp")
        self.assertFalse(ok)

    def test_cloud_metadata_ip_is_blocked(self):
        ok, reason = is_safe_url("http://169.254.169.254/latest/meta-data")
        self.assertFalse(ok)
        self.assertIn("169.254", reason)

    def test_non_http_scheme_is_blocked(self):
        ok, reason = is_safe_url("file:///etc/passwd")
        self.assertFalse(ok)
        self.assertIn("scheme", reason)

    def test_missing_host_is_blocked(self):
        ok, reason = is_safe_url("http://")
        self.assertFalse(ok)
        self.assertIn("host", reason)

    def test_allowlist_override_permits_loopback(self):
        with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_SSRF_ALLOW": "127.0.0.1"}):
            ok, reason = is_safe_url("http://127.0.0.1:9000/mcp")
        self.assertTrue(ok, reason)

    def test_hostname_resolving_to_private_is_blocked(self):
        ok, _ = is_safe_url("http://localhost:3000/mcp")
        self.assertFalse(ok)

    def test_cgnat_range_is_blocked(self):
        ok, _ = is_safe_url("http://100.64.0.1/mcp")
        self.assertFalse(ok)

    def test_ipv4_mapped_ipv6_loopback_is_blocked(self):
        ok, _ = is_safe_url("http://[::ffff:7f00:1]/mcp")  # ::ffff:127.0.0.1
        self.assertFalse(ok)


from mcp_newsletter.netguard import read_capped, MAX_RESPONSE_BYTES


class ReadCappedTests(unittest.TestCase):
    def test_reads_small_body_fully(self):
        body = read_capped(io.BytesIO(b"hello"), limit=100)
        self.assertEqual(body, b"hello")

    def test_aborts_when_body_exceeds_limit(self):
        with self.assertRaises(ValueError) as ctx:
            read_capped(io.BytesIO(b"x" * 50), limit=10)
        self.assertIn("exceeded", str(ctx.exception))

    def test_reads_body_exactly_at_limit(self):
        body = read_capped(io.BytesIO(b"x" * 10), limit=10)
        self.assertEqual(len(body), 10)

    def test_reassembles_multiple_chunks(self):
        class Chunked:
            def __init__(self, parts):
                self._parts = list(parts)
            def read(self, n=-1):
                return self._parts.pop(0) if self._parts else b""
        body = read_capped(Chunked([b"ab", b"cd", b"ef"]), limit=100)
        self.assertEqual(body, b"abcdef")

    def test_default_limit_is_five_mib(self):
        self.assertEqual(MAX_RESPONSE_BYTES, 5 * 1024 * 1024)


from mcp_newsletter.netguard import RetryPolicy, should_retry


class ShouldRetryTests(unittest.TestCase):
    def setUp(self):
        self.policy = RetryPolicy(max_retries=3, base_delay=0.5, max_delay=8.0)

    def test_no_retry_after_max_attempts(self):
        retry, _ = should_retry(self.policy, attempt=3, status=503, retry_after=None)
        self.assertFalse(retry)

    def test_retries_on_429(self):
        retry, delay = should_retry(self.policy, attempt=0, status=429, retry_after=None)
        self.assertTrue(retry)
        self.assertEqual(delay, 0.5)

    def test_retries_on_5xx(self):
        retry, _ = should_retry(self.policy, attempt=1, status=502, retry_after=None)
        self.assertTrue(retry)

    def test_does_not_retry_on_404(self):
        retry, _ = should_retry(self.policy, attempt=0, status=404, retry_after=None)
        self.assertFalse(retry)

    def test_honors_retry_after_header(self):
        retry, delay = should_retry(self.policy, attempt=0, status=429, retry_after=5.0)
        self.assertTrue(retry)
        self.assertEqual(delay, 5.0)

    def test_no_retry_when_attempt_exceeds_max(self):
        retry, delay = should_retry(self.policy, attempt=10, status=503, retry_after=None)
        self.assertFalse(retry)

    def test_delay_capped_at_max_delay(self):
        policy = RetryPolicy(max_retries=5, base_delay=1.0, max_delay=4.0)
        # attempt=4 -> uncapped 1.0*2**4 = 16.0, must be capped to 4.0
        retry, delay = should_retry(policy, attempt=4, status=503, retry_after=None)
        self.assertTrue(retry)
        self.assertEqual(delay, 4.0)

    def test_backoff_grows_then_caps(self):
        _, delay = should_retry(self.policy, attempt=2, status=503, retry_after=None)
        self.assertEqual(delay, 2.0)

    def test_network_error_retries_when_status_none(self):
        retry, delay = should_retry(self.policy, attempt=0, status=None, retry_after=None)
        self.assertTrue(retry)
        self.assertEqual(delay, 0.5)


class MaxResponseBytesTests(unittest.TestCase):
    def test_zero_env_value_falls_back_to_default(self):
        from mcp_newsletter.netguard import MAX_RESPONSE_BYTES, max_response_bytes
        with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_MAX_RESPONSE_BYTES": "0"}):
            self.assertEqual(max_response_bytes(), MAX_RESPONSE_BYTES)

    def test_positive_env_value_is_used(self):
        from mcp_newsletter.netguard import max_response_bytes
        with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_MAX_RESPONSE_BYTES": "1234"}):
            self.assertEqual(max_response_bytes(), 1234)


if __name__ == "__main__":
    unittest.main()
