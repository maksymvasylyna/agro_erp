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
