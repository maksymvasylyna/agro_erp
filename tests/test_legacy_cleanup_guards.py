"""Safeguards for exact, one-time legacy cleanup; no production DB access."""
import unittest

from scripts.cleanup_legacy_products_requests_2026 import (
    assert_expected_identifiers,
    ARCHIVED_PRODUCT_IDS,
    NEW_PRODUCT_IDS,
    OLD_ALLOCATION_IDS,
    OLD_REQUEST_IDS,
    OLD_REQUEST_ITEM_IDS,
)


def baseline():
    return {
        "archived_products": ARCHIVED_PRODUCT_IDS,
        "active_products": NEW_PRODUCT_IDS,
        "payer_allocations": OLD_ALLOCATION_IDS,
        "shipment_requests": OLD_REQUEST_IDS,
        "shipment_request_items": OLD_REQUEST_ITEM_IDS,
        "plans": (),
        "treatments": (),
        "plan_treatments": (),
        "stock_transactions": (),
        "payment_inbox": (),
    }


class LegacyCleanupGuardsTest(unittest.TestCase):
    def test_verified_baseline_passes(self):
        assert_expected_identifiers(baseline())
        self.assertEqual(49, len(ARCHIVED_PRODUCT_IDS))
        self.assertEqual(108, len(NEW_PRODUCT_IDS))
        self.assertEqual(108, len(OLD_ALLOCATION_IDS))
        self.assertEqual(4, len(OLD_REQUEST_IDS))
        self.assertEqual(9, len(OLD_REQUEST_ITEM_IDS))

    def test_cannot_delete_newly_created_plan(self):
        state = baseline()
        state["plans"] = (1,)
        with self.assertRaises(RuntimeError):
            assert_expected_identifiers(state)

    def test_cannot_delete_new_product(self):
        state = baseline()
        state["active_products"] = (*NEW_PRODUCT_IDS, 161)
        with self.assertRaises(RuntimeError):
            assert_expected_identifiers(state)

    def test_cannot_delete_unexpected_request(self):
        state = baseline()
        state["shipment_requests"] = (1, 2, 3, 4, 5)
        with self.assertRaises(RuntimeError):
            assert_expected_identifiers(state)

    def test_cannot_delete_modified_purchase_allocations(self):
        state = baseline()
        state["payer_allocations"] = OLD_ALLOCATION_IDS[1:]
        with self.assertRaises(RuntimeError):
            assert_expected_identifiers(state)


if __name__ == "__main__":
    unittest.main()
