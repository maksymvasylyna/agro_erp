# AgroERP historical field references (2020–2026)

Source: [Основний файл даних про поля](https://docs.google.com/spreadsheets/d/11fBHfms8PE-EeeGtXj_RexoFd_yxBxP0p8RueaT94uw/edit), `Історія полів` worksheet.
Cluster mapping: existing test PostgreSQL `agro_erp_test` (16 entities).

Verified 2026-11-16: 839 physical field identities, 27 enterprises across 2017–2027; for 2020–2026 there are 3937 field-season planting source records across 17 distinct enterprise names.
One 2020-only enterprise, `Агроконтракт-Н(проект) ТОВ` (7 seasonal records, 11 fields overall), is kept as its own company in Cluster 1 rather than merged with `Агроконтракт-Н 2021 ТОВ`. This cluster association is inferred from its company affiliation, not from an explicit column in the source worksheet.

## Existing cluster alignment
- `Кластер 1`: 10 historical enterprises including the 2020 project.
- `Кластер 2`: 3.
- `Кластер 3`: 3.
- `Миколаївське`: 1.
- Preserve existing cluster IDs, including rename of `ТОВ ПрАТ Миколаївське` to `Миколаївське`.

## Crops
Existing production crops: `Горох зимуючий`, `Кукурудза на зерно`, `Кукурудза на силос`, `Пшениця озима`, `Ріпак озимий`, `Соняшник`.
Additional crops for 2020–2026: Буряк цукровий, Пар, Соя, Сорго цукрове, Ячмінь ярий, Жито озиме на силос, Пшениця яра.

Historical source `Кукурудза` is mapped to already existing `Кукурудза на зерно` (because the source separately records maize for silage). `Соняшник сторонній` is a special note and should map to `Соняшник` with the source wording in `field_plantings.note`, not an extra crop. Do not merge 2027 source `Горох озимий` with production `Горох зимуючий` without separate verification.

## Safety
- This one-off migration updates ONLY reference names and missing companies, cultures and empty seasons 2020–2025.
- Does **not** touch `fields`, `field_seasons`, `field_plantings`, purchases, plans, or any 2026/2027 season.
- Preserves all existing primary keys and relationships. Conflicts abort the synchronization rather than guess.
- Never wipes test data, historical records, or the placeholder company `1111119`.
- Enable temporarily with `AGROERP_SYNC_FIELD_REFS_2020_2026=1` on the **main production** Render service. Reset to `0` after verification.
