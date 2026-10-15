"""Historical evidence is immutable; reviewed revisions reject later drift."""
import hashlib
import unittest
from integration.naming.config_compatibility import assert_reviewed_asset


class ReviewedAssetTests(unittest.TestCase):
    def test_revised_asset_is_exact_and_cannot_replace_original_evidence(self):
        value=b'pre-existing revision'
        record={'scope':'preserved_preexisting_revision','original_sha256':'frozen',
                'effective_sha256':hashlib.sha256(value).hexdigest()}
        assert_reviewed_asset(value,record,'frozen')
        with self.assertRaisesRegex(AssertionError,'revision changed'):
            assert_reviewed_asset(value+b'changed',record,'frozen')
        with self.assertRaisesRegex(AssertionError,'historical source evidence'):
            assert_reviewed_asset(value,record,'new-original')
