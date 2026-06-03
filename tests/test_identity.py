import unittest

from mcp_newsletter.identity import canonical_key, canonical_repo


class CanonicalRepoTests(unittest.TestCase):
    def test_strips_scheme_git_suffix_and_trailing_slash(self):
        self.assertEqual(canonical_repo("https://GitHub.com/Acme/Solo.git/"),
                         "github.com/acme/solo")

    def test_strips_www(self):
        self.assertEqual(canonical_repo("https://www.github.com/acme/solo"),
                         "github.com/acme/solo")

    def test_strips_tree_and_blob_suffixes(self):
        self.assertEqual(canonical_repo("github.com/acme/solo/tree/main"),
                         "github.com/acme/solo")
        self.assertEqual(canonical_repo("github.com/acme/solo/blob/main/README.md"),
                         "github.com/acme/solo")

    def test_empty_is_empty(self):
        self.assertEqual(canonical_repo(""), "")
        self.assertEqual(canonical_repo(None), "")

    def test_variants_collapse_to_one(self):
        variants = [
            "https://github.com/acme/solo",
            "http://github.com/acme/solo/",
            "https://www.github.com/Acme/Solo.git",
            "github.com/acme/solo/tree/main",
        ]
        self.assertEqual(len({canonical_repo(v) for v in variants}), 1)


class CanonicalKeyTests(unittest.TestCase):
    def test_official_name_wins(self):
        self.assertEqual(
            canonical_key(official_name="io.github.acme/Slack",
                          repo_url="https://github.com/acme/slack"),
            "io.github.acme/slack")

    def test_repo_root(self):
        self.assertEqual(canonical_key(repo_url="https://github.com/acme/solo"),
                         "repo:github.com/acme/solo")

    def test_repo_subpath(self):
        self.assertEqual(
            canonical_key(repo_url="https://github.com/mcp/servers", subpath="src/fetch"),
            "repo:github.com/mcp/servers#src/fetch")

    def test_repo_variants_share_key(self):
        a = canonical_key(repo_url="https://www.github.com/acme/solo.git")
        b = canonical_key(repo_url="github.com/acme/solo/tree/main")
        self.assertEqual(a, b)

    def test_fallback_to_source_slug(self):
        self.assertEqual(canonical_key(source="glama", source_id="Acme/Slack"),
                         "glama:acme-slack")


if __name__ == "__main__":
    unittest.main()
