# Historical field import (2020–2026)

This program expects a **private** temporary data payload from the canonical Google Sheet (tab `Історія полів`). The public GitHub repository MUST NOT contain field-level source rows.

Expected source metrics:

| Harvest year | Records | Physical sown area, ha |
| --- | ---: | ---: |
| 2020 | 549 | 36,477.97 |
| 2021 | 573 | 36,410.63 |
| 2022 | 560 | 35,949.20 |
| 2023 | 582 | 35,751.73 |
| 2024 | 560 | 35,195.66 |
| 2025 | 563 | 34,686.88 |
| 2026 | 550 | 34,443.91 |

Totals: 715 unique company+field identities, 3,937 field-season/planting rows, 17 companies. Single crop allocation per field per year in the source. Main source covers 839 fields across 2017–2027; the subset for 2020–2026 contains 715.

Imports to `fields`, `field_seasons`, `field_plantings` and one metadata state table. Existing active field IDs and all plan links are retained. `fields.area` / `fields.culture_id` for existing fields are left unchanged, while new fields get their latest 2020–2026 snapshot values. Season links for 2020–2026 become source-authoritative; obsolete pre-import seasonal links are removed. Season 2027 and plans/purchases are untouched.

Crop semantics:
- `Кукурудза` -> existing `Кукурудза на зерно` (silage is separately represented in source).
- `Соняшник сторонній` -> `Соняшник`, keeping original marker in `field_plantings.note`.
- Other source labels map exactly to the updated reference catalog.

The importer refuses incomplete input, incorrect annual counts/totals, duplicate field keys, missing companies/cultures, or an unexpected pre-existing different import checksum. It serializes production multi-worker startup with a PostgreSQL advisory lock and uses one transaction for all changes. Repeating the same import skips.

One-time configuration (only for the production Render service):
`AGROERP_FIELD_HISTORY_DATA_000`, `AGROERP_FIELD_HISTORY_DATA_001`, ... plus `AGROERP_FIELD_HISTORY_PARTS` and `AGROERP_FIELD_HISTORY_CHECKSUM`. Enable `AGROERP_FIELD_HISTORY_IMPORT=1`; after successful validation set it to `0` and clear all data chunks and metadata environment variables.

**No field-level source data should ever be committed to this GitHub repository, written to application logs, or added to a publicly exposed route.**
