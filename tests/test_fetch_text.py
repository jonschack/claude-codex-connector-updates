import unittest
from unittest import mock
from urllib.error import HTTPError

from mcp_newsletter import utils


def _resp(body=b"ok", content_type="text/html"):
    r = mock.MagicMock()
    _buf = [body]

    def _read(n=-1):
        if not _buf[0]:
            return b""
        if n and n > 0:
            chunk = _buf[0][:n]
            _buf[0] = _buf[0][n:]
            return chunk
        chunk = _buf[0]
        _buf[0] = b""
        return chunk

    r.read.side_effect = _read
    r.headers.get_content_charset.return_value = "utf-8"
    r.headers.get.side_effect = lambda k, d="": {"content-type": content_type}.get(k.lower(), d)
    r.status = 200
    r.__enter__ = lambda s: s
    r.__exit__ = lambda s, *a: False
    return r


class FetchTextRetryTests(unittest.TestCase):
    def test_succeeds_first_try(self):
        with mock.patch.object(utils, "urlopen", return_value=_resp(b"hello")):
            text, meta = utils.fetch_text("https://8.8.8.8/x")
        self.assertEqual(text, "hello")
        self.assertEqual(meta["error"], "")

    def test_retries_on_503_then_succeeds(self):
        calls = []
        def fake_urlopen(req, timeout=20):
            if not calls:
                calls.append(1)
                raise HTTPError("https://8.8.8.8/x", 503, "busy", {}, None)
            return _resp(b"recovered")
        with mock.patch.object(utils, "urlopen", side_effect=fake_urlopen), \
             mock.patch.object(utils, "_sleep") as sleeper:
            text, meta = utils.fetch_text("https://8.8.8.8/x")
        self.assertEqual(text, "recovered")
        sleeper.assert_called()

    def test_gives_up_after_max_retries_on_503(self):
        def always_503(req, timeout=20):
            raise HTTPError("https://8.8.8.8/x", 503, "busy", {}, None)
        with mock.patch.object(utils, "urlopen", side_effect=always_503), \
             mock.patch.object(utils, "_sleep"):
            text, meta = utils.fetch_text("https://8.8.8.8/x")
        self.assertEqual(meta["status"], 503)
        self.assertNotEqual(meta["error"], "")

    def test_does_not_retry_on_404(self):
        attempts = []
        def once_404(req, timeout=20):
            attempts.append(1)
            raise HTTPError("https://8.8.8.8/x", 404, "nope", {}, None)
        with mock.patch.object(utils, "urlopen", side_effect=once_404), \
             mock.patch.object(utils, "_sleep"):
            utils.fetch_text("https://8.8.8.8/x")
        self.assertEqual(len(attempts), 1)

    def test_oversized_body_fails_fast_without_retry(self):
        attempts = []
        def big_urlopen(req, timeout=20):
            attempts.append(1)
            return _resp(b"x" * 10_000)
        with mock.patch.dict("os.environ", {"MCP_NEWSLETTER_MAX_RESPONSE_BYTES": "100"}), \
             mock.patch.object(utils, "urlopen", side_effect=big_urlopen), \
             mock.patch.object(utils, "_sleep") as sleeper:
            text, meta = utils.fetch_text("https://8.8.8.8/x")
        self.assertIsNone(text)
        self.assertIn("exceeded", meta["error"])
        self.assertEqual(len(attempts), 1)   # no re-fetch of the oversized body
        sleeper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
