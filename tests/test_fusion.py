import unittest

from mcp_newsletter.fusion import fuse


class FusionTests(unittest.TestCase):
    def test_url_variants_collapse_with_corroboration(self):
        items = [
            {"url": "https://github.com/acme/x", "tier": "declared_manifest", "source": "registry"},
            {"url": "https://www.github.com/acme/x.git", "tier": "claimed_description", "source": "npm"},
            {"url": "github.com/acme/x/tree/main", "tier": "verified_tools", "source": "registry_probe"},
        ]
        fused = fuse(items)
        self.assertEqual(len(fused), 1)               # all variants collapse to one row
        rec = next(iter(fused.values()))
        self.assertEqual(rec.corroboration, 3)         # three distinct tiers
        self.assertEqual(rec.best_tier, "verified_tools")
        self.assertEqual(len(rec.urls), 3)

    def test_engagement_source_excluded_from_corroboration(self):
        items = [
            {"url": "https://github.com/acme/y", "tier": "declared_manifest", "source": "registry"},
            {"url": "https://github.com/acme/y", "tier": "none", "source": "grok"},  # viral
        ]
        rec = next(iter(fuse(items).values()))
        self.assertEqual(rec.corroboration, 1)          # grok does not corroborate
        self.assertIn("grok", rec.sources)              # but provenance is kept

    def test_distinct_repos_not_merged(self):
        items = [
            {"url": "https://github.com/acme/a", "tier": "claimed_description", "source": "npm"},
            {"url": "https://github.com/acme/b", "tier": "claimed_description", "source": "npm"},
        ]
        self.assertEqual(len(fuse(items)), 2)

    def test_no_repo_items_keyed_separately(self):
        items = [
            {"url": "", "tier": "claimed_description", "source": "npm"},
            {"url": "", "tier": "claimed_description", "source": "pypi"},
        ]
        self.assertEqual(len(fuse(items)), 2)  # not collapsed into one empty bucket


if __name__ == "__main__":
    unittest.main()
