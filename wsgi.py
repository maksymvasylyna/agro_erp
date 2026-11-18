from app import create_app

app = create_app()

# Explicit one-time, idempotent migration for the MAIN Render service only.
# The variable is set by the administrator on the production service, then
# reset to zero after verifying the reference dictionaries.
import os
if os.environ.get("AGROERP_SYNC_FIELD_REFS_2020_2026") == "1":
    from scripts.sync_field_history_references import sync_reference_dictionaries
    with app.app_context():
        report = sync_reference_dictionaries(dry_run=False)
        app.logger.warning("AgroERP historical reference synchronization: %s", report)


# Data is securely staged through temporary Render environment variables,
# NOT in this public repository. A transaction and checksum guard both the
# import and any repeated gunicorn worker startups.
if os.environ.get("AGROERP_FIELD_HISTORY_IMPORT") == "1":
    from scripts.import_field_history_2020_2026 import import_from_environment
    with app.app_context():
        result = import_from_environment()
        app.logger.warning("AgroERP 2020-2026 field history import: %s", result)


# Explicit ONE-TIME cleanup of pre-July 2026 demo products and transactions.
# Runs only when the operator sets the exact temporary Render flag.
# Preserves the new Syngenta catalog, field data and every unrelated module.
if os.environ.get("AGROERP_CLEAN_2026_LEGACY_ONCE") == (
    "DELETE_49_PRODUCTS_108_ALLOCATIONS_4_REQUESTS_9_LINES_20261118"
):
    from scripts.cleanup_legacy_products_requests_2026 import run_once
    with app.app_context():
        app.logger.warning("AgroERP legacy cleanup: %s", run_once())
