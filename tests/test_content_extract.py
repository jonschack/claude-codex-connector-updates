import unittest

from mcp_newsletter.content_extract import extract_main_text


CLAUDE_LIKE = """
<html><head><title>Acme | Claude</title></head><body>
<nav>Meet Claude Products Claude Claude Code Claude Cowork Pricing Try Claude Contact sales</nav>
<header>Try Claude Contact sales</header>
<main>
  <h1>Acme</h1>
  <p>Acme connects Claude to your warehouse to query and update inventory in real time.</p>
</main>
<footer>Try Claude Contact sales Anthropic news</footer>
</body></html>
"""

NO_MAIN = """
<html><body>
<nav>Home About Contact</nav>
<div class="content"><p>Just the body text we want here.</p></div>
<script>var x = 'Contact sales';</script>
</body></html>
"""


class ContentExtractTests(unittest.TestCase):
    def test_pulls_main_drops_nav_and_footer(self):
        text = extract_main_text(CLAUDE_LIKE)
        self.assertIn("warehouse to query and update inventory", text)
        self.assertNotIn("Contact sales", text)
        self.assertNotIn("Anthropic news", text)

    def test_falls_back_to_body_without_main(self):
        text = extract_main_text(NO_MAIN)
        self.assertIn("Just the body text we want here", text)
        # nav and script content are still stripped in the fallback path
        self.assertNotIn("Contact sales", text)
        self.assertNotIn("Home About Contact", text)

    def test_empty_markup_is_empty(self):
        self.assertEqual(extract_main_text(""), "")

    def test_empty_main_falls_back_to_body_content(self):
        # an empty <main> must not lose content that lives elsewhere in the body
        markup = '<html><body><main></main><div class="desc">The real description lives here.</div></body></html>'
        text = extract_main_text(markup)
        self.assertIn("The real description lives here", text)


if __name__ == "__main__":
    unittest.main()
