"""Remove ONLY the 2026 legacy demo inventory and its dependent transaction rows.

One-use production maintenance. All target row identities and counts must match
the inspected baseline; no fields, sowing, cultures, seasons or new Syngenta
product IDs are touched. Full row-level backups commit atomically with deletion.
"""
import os

from flask import current_app
from sqlalchemy import text

from extensions import db

FLAG = "AGROERP_CLEAN_2026_LEGACY_ONCE"
VALUE = "DELETE_49_PRODUCTS_108_ALLOCATIONS_4_REQUESTS_9_LINES_20261118"
KEY = "cleanup_legacy_demo_products_requests_2026_11_18_v1"

ARCHIVED_PRODUCT_IDS = (
    2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
    19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
    33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47,
    48, 49, 50, 51, 52,
)
NEW_PRODUCT_IDS = tuple(range(53, 161))
OLD_ALLOCATION_IDS = tuple(range(450, 558))
OLD_REQUEST_IDS = tuple(range(1, 5))
OLD_REQUEST_ITEM_IDS = tuple(range(1, 10))


def assert_expected_identifiers(actual):
    """Fail closed if any ID differs from the verified production baseline."""
    expected = {
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
    for key, ids in expected.items():
        if tuple(actual.get(key, ())) != ids:
            raise RuntimeError(
                f"Legacy cleanup cancelled: unexpected identities in {key} "
                f"(expected {len(ids)}, got {len(actual.get(key, ()))})"
            )


def run_once():
    if os.environ.get(FLAG) != VALUE:
        return {"status": "not_requested"}
    if db.engine.dialect.name != "postgresql":
        return {"status": "unsupported_engine"}

    try:
        with db.engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '15s'"))
            conn.execute(text("SELECT pg_advisory_xact_lock(381542, 20261118)"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.agroerp_legacy_cleanup_backups (
                    operation_key text PRIMARY KEY,
                    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    payload jsonb NOT NULL,
                    summary jsonb NOT NULL
                )
            """))
            already = conn.execute(text("""
                SELECT 1 FROM public.agroerp_legacy_cleanup_backups
                WHERE operation_key=:key
            """), {"key": KEY}).scalar()
            if already:
                return {"status": "already_executed"}

            # Prevent concurrent app changes between count guards and deletion.
            conn.execute(text("""
                LOCK TABLE public.products, public.payer_allocations,
                    public.shipment_requests, public.shipment_request_items,
                    public.plans, public.treatments, public.plan_treatments,
                    public.stock_transactions, public.payment_inbox,
                    public.product_ingredients
                IN SHARE ROW EXCLUSIVE MODE
            """))

            sets = {
                "archived_products": "SELECT id FROM public.products WHERE is_archived ORDER BY id",
                "active_products": "SELECT id FROM public.products WHERE NOT is_archived ORDER BY id",
                "payer_allocations": "SELECT id FROM public.payer_allocations ORDER BY id",
                "shipment_requests": "SELECT id FROM public.shipment_requests ORDER BY id",
                "shipment_request_items": "SELECT id FROM public.shipment_request_items ORDER BY id",
                "plans": "SELECT id FROM public.plans ORDER BY id",
                "treatments": "SELECT id FROM public.treatments ORDER BY id",
                "plan_treatments": "SELECT id FROM public.plan_treatments ORDER BY id",
                "stock_transactions": "SELECT id FROM public.stock_transactions ORDER BY id",
                "payment_inbox": "SELECT id FROM public.payment_inbox ORDER BY id",
            }
            actual = {key: tuple(row[0] for row in conn.execute(text(q)))
                      for key, q in sets.items()}
            assert_expected_identifiers(actual)

            # All old purchase allocations and request lines must be tied
            # exclusively to archived products. No rows later than June 2026.
            restrictions = conn.execute(text("""
                SELECT
                  (SELECT count(*) FROM payer_allocations a
                   JOIN products p ON p.id=a.product_id
                   WHERE NOT p.is_archived OR a.created_at >= DATE '2026-07-01')
                     AS unexpected_allocations,
                  (SELECT count(*) FROM shipment_request_items i
                   JOIN products p ON p.id=i.product_id
                   WHERE NOT p.is_archived) AS unexpected_request_items,
                  (SELECT count(*) FROM shipment_requests
                   WHERE status <> 'executed'
                      OR created_at >= DATE '2026-07-01') AS unexpected_requests,
                  (SELECT count(*) FROM product_ingredients i
                   JOIN products p ON p.id=i.product_id
                   WHERE p.is_archived) AS archived_ingredients,
                  (SELECT count(*) FROM products) AS all_products
            """)).mappings().one()
            if restrictions["all_products"] != 157 or any(
                restrictions[k] for k in (
                    "unexpected_allocations",
                    "unexpected_request_items",
                    "unexpected_requests",
                    "archived_ingredients",
                )
            ):
                raise RuntimeError(f"Legacy cleanup cancelled by relationship guard: {dict(restrictions)}")

            # Back up exact rows within the SAME transaction as DELETE.
            conn.execute(text("""
                INSERT INTO public.agroerp_legacy_cleanup_backups
                    (operation_key, payload, summary)
                SELECT :key,
                  jsonb_build_object(
                    'products', (SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.id),
                        '[]'::jsonb) FROM products p WHERE p.is_archived),
                    'payer_allocations', (SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY a.id),
                        '[]'::jsonb) FROM payer_allocations a),
                    'shipment_requests', (SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.id),
                        '[]'::jsonb) FROM shipment_requests r),
                    'shipment_request_items', (SELECT coalesce(jsonb_agg(to_jsonb(i) ORDER BY i.id),
                        '[]'::jsonb) FROM shipment_request_items i),
                    'product_ingredients', (SELECT coalesce(jsonb_agg(to_jsonb(i) ORDER BY i.id),
                        '[]'::jsonb) FROM product_ingredients i
                        JOIN products p ON p.id=i.product_id WHERE p.is_archived),
                    'plans', '[]'::jsonb,
                    'treatments', '[]'::jsonb,
                    'plan_treatments', '[]'::jsonb,
                    'stock_transactions', '[]'::jsonb,
                    'payment_inbox', '[]'::jsonb
                  ),
                  jsonb_build_object(
                    'archived_products', 49, 'payer_allocations', 108,
                    'shipment_requests', 4, 'shipment_request_items', 9,
                    'active_products_kept', 108
                  )
            """), {"key": KEY})

            # Delete child records first, then parent requests and products.
            deleted_allocations = conn.execute(text("""
                DELETE FROM public.payer_allocations
                WHERE product_id IN (SELECT id FROM products WHERE is_archived)
            """)).rowcount
            deleted_lines = conn.execute(text("""
                DELETE FROM public.shipment_request_items
                WHERE product_id IN (SELECT id FROM products WHERE is_archived)
            """)).rowcount
            deleted_requests = conn.execute(text("""
                DELETE FROM public.shipment_requests
                WHERE id BETWEEN 1 AND 4
                  AND NOT EXISTS (SELECT 1 FROM shipment_request_items i
                                  WHERE i.request_id=shipment_requests.id)
            """)).rowcount
            deleted_products = conn.execute(text("""
                DELETE FROM public.products WHERE is_archived
            """)).rowcount
            result = {
                "archived_products_deleted": deleted_products,
                "payer_allocations_deleted": deleted_allocations,
                "shipment_requests_deleted": deleted_requests,
                "shipment_request_items_deleted": deleted_lines,
            }
            if result != {
                "archived_products_deleted": 49,
                "payer_allocations_deleted": 108,
                "shipment_requests_deleted": 4,
                "shipment_request_items_deleted": 9,
            }:
                raise RuntimeError(f"Legacy cleanup rolled back: unexpected delete count {result}")

            after = conn.execute(text("""
                SELECT (SELECT count(*) FROM products) AS products,
                       (SELECT count(*) FROM products WHERE is_archived) AS archived,
                       (SELECT count(*) FROM payer_allocations) AS allocations,
                       (SELECT count(*) FROM shipment_requests) AS requests,
                       (SELECT count(*) FROM shipment_request_items) AS lines,
                       (SELECT count(*) FROM plans) AS plans
            """)).mappings().one()
            if dict(after) != {
                "products": 108, "archived": 0, "allocations": 0,
                "requests": 0, "lines": 0, "plans": 0,
            }:
                raise RuntimeError(f"Legacy cleanup rolled back: wrong final counts {dict(after)}")
            # Successful exit commits BOTH the backup and all deletions.
            return {"status": "completed", **result, "active_products_kept": 108}
    except Exception:
        current_app.logger.exception("2026 legacy cleanup failed; transaction rolled back")
        return {"status": "failed_rolled_back"}
