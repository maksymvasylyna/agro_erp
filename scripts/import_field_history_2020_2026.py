"""One-time audited import of 2020–2026 field rotation from private Render env.

The canonical source is "Основний файл даних про поля" / "Історія полів".
The source rows are NEVER stored in the public GitHub repository.
Run only with AGROERP_FIELD_HISTORY_IMPORT=1 and DATA_000... environment
variables. All history mutations and validation happen in one transaction.

The 2027 season and pre-existing non-seasonal plan/purchase relationships
are preserved. Only obsolete *season assignments* from 2020–2026 are removed
so these years match the original source, rather than the old test content.
"""
import json
import os
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import delete, func, insert, select, text

from extensions import db
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.field_models import Field
from modules.reference.fields.season_models import Season, FieldSeason, FieldPlanting

START_YEAR, END_YEAR = 2020, 2026
STATE_KEY = "source-history-2020-2026"
EXPECTED_STATS = {
    2020: (549, 3647797),
    2021: (573, 3641063),
    2022: (560, 3594920),
    2023: (582, 3575173),
    2024: (560, 3519566),
    2025: (563, 3468688),
    2026: (550, 3444391),
}
EXPECTED_FIELDS = 715
EXPECTED_ORGANIZATIONS = 17
CROP_MAPPING = {
    "Кукурудза": "Кукурудза на зерно",
    "Соняшник сторонній": "Соняшник",
}


def _norm(value):
    return " ".join((value or "").split()).casefold()


def _checksum(s):
    """Lightweight transfer-corruption check over Unicode code points."""
    a, b = 1, 0
    for character in s:
        a = (a + ord(character)) % 65521
        b = (b + a) % 65521
    return f"{(b << 16) | a:08x}"


def _parse_and_validate(raw, *, expected_stats, expected_fields, expected_organizations):
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("Невідома версія пакета історії.")
    organizations = payload.get("organizations")
    crops = payload.get("crops")
    fields = payload.get("fields")
    if not isinstance(organizations, list) or not isinstance(crops, list) or not isinstance(fields, list):
        raise ValueError("Неповний пакет історії.")
    if len(organizations) != expected_organizations or len(set(organizations)) != len(organizations):
        raise ValueError("Невірна кількість підприємств у джерелі.")
    if len(set(crops)) != len(crops):
        raise ValueError("Дублікати культур у джерелі.")
    if len(fields) != expected_fields:
        raise ValueError("Невідповідна кількість фізичних полів.")
    if any(not isinstance(x, str) or not x.strip() for x in organizations + crops):
        raise ValueError("Порожня назва підприємства або культури.")

    seen, actual = set(), defaultdict(lambda: [0, 0])
    seasonal_keys = set()
    for item in fields:
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError("Невірна структура запису поля.")
        company_idx, code, rotations = item
        if (not type(company_idx) is int or company_idx < 0
                or company_idx >= len(organizations) or not isinstance(code, str)
                or not code.strip() or len(code) > 255
                or not isinstance(rotations, list) or not rotations):
            raise ValueError("Невірний ідентифікатор або перелік сезонів поля.")
        key = (organizations[company_idx], _norm(code))
        if key in seen:
            raise ValueError("Дубль поля в джерелі.")
        seen.add(key)
        for row in rotations:
            if not isinstance(row, list) or len(row) != 3:
                raise ValueError("Невірний сезонний рядок.")
            year, cents, crop_idx = row
            if (type(year) is not int or not START_YEAR <= year <= END_YEAR
                    or type(cents) is not int or cents <= 0
                    or type(crop_idx) is not int or not 0 <= crop_idx < len(crops)):
                raise ValueError("Невірний рік, площа або культура.")
            identity = (key, year)
            if identity in seasonal_keys:
                raise ValueError("Два записи одного поля в одному році.")
            seasonal_keys.add(identity)
            actual[year][0] += 1
            actual[year][1] += cents
    if dict(actual) != {int(y): list(v) for y, v in expected_stats.items()}:
        raise ValueError("Річні площі та кількість записів не збігаються з джерелом.")
    if len({key[0][0] for key in seasonal_keys}) != expected_organizations:
        raise ValueError("Не всі підприємства мають сезонні записи.")
    if len(seasonal_keys) != sum(v[0] for v in expected_stats.values()):
        raise ValueError("Невірна кількість сезонних записів.")
    if payload.get("stats") != {
        str(year): [count, area] for year, (count, area) in expected_stats.items()
    }:
        raise ValueError("Контрольна статистика пакета пошкоджена.")
    return payload


def import_history_text(raw, *, source_checksum=None,
                        expected_stats=EXPECTED_STATS,
                        expected_fields=EXPECTED_FIELDS,
                        expected_organizations=EXPECTED_ORGANIZATIONS):
    """Validate, reconcile and commit the entire archive atomically."""
    checksum = _checksum(raw)
    if source_checksum is not None and checksum != source_checksum:
        raise ValueError("Помилка перевірки цілісності пакета історії.")
    payload = _parse_and_validate(
        raw, expected_stats=expected_stats,
        expected_fields=expected_fields,
        expected_organizations=expected_organizations,
    )

    try:
        # Serialize multi-worker startup and prevent duplicate imports.
        if db.session.get_bind().dialect.name == "postgresql":
            db.session.execute(text("SELECT pg_advisory_xact_lock(1847351, 20202026)"))
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS agroerp_history_import_state (
                name VARCHAR(80) PRIMARY KEY,
                checksum VARCHAR(32) NOT NULL,
                imported_rows INTEGER NOT NULL,
                imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        recorded = db.session.execute(
            text("SELECT checksum FROM agroerp_history_import_state WHERE name = :name"),
            {"name": STATE_KEY},
        ).scalar_one_or_none()
        if recorded == checksum:
            db.session.commit()
            return {"skipped": True, "reason": "already imported", "source_checksum": checksum}
        if recorded is not None:
            raise ValueError(
                "Інша версія історії вже імпортована. Потрібна окрема узгоджена процедура оновлення."
            )

        organizations = {item.name: item for item in Company.query.all()}
        if len(organizations) != Company.query.count():
            raise ValueError("У довіднику підприємств є дублікати назв.")
        crops = {_norm(item.name): item for item in Culture.query.all()}
        seasons = {item.year: item for item in Season.query.all()}
        for name in payload["organizations"]:
            if name not in organizations:
                raise ValueError("Немає підприємства в довіднику: " + name)
        for crop in payload["crops"]:
            if _norm(CROP_MAPPING.get(crop, crop)) not in crops:
                raise ValueError("Немає культури в довіднику: " + crop)
        for year in expected_stats:
            if year not in seasons:
                raise ValueError(f"Не створено сезон {year}.")

        # Active existing fields retain their IDs, legacy area/crop and all
        # links to plans. Archived ones are left alone.
        existing = {}
        for field in Field.query.filter(Field.is_active.is_(True)).all():
            k = (field.company_id, _norm(field.name))
            if k in existing:
                raise ValueError("Два активні поля з однаковим номером на підприємстві.")
            existing[k] = field

        current = (
            FieldSeason.query.join(Season, FieldSeason.season_id == Season.id)
            .filter(Season.year >= START_YEAR, Season.year <= END_YEAR)
            .all()
        )
        current_map = {(x.season_id, x.field_id): x for x in current}
        if len(current_map) != len(current):
            raise ValueError("Дублікати сезонних записів у робочій базі.")

        field_rows = []
        created_fields = 0
        for org_idx, field_code, rotations in payload["fields"]:
            company = organizations[payload["organizations"][org_idx]]
            k = (company.id, _norm(field_code))
            field = existing.get(k)
            if field is None:
                latest = max(rotations, key=lambda item: item[0])
                year, cents, crop_idx = latest
                name = CROP_MAPPING.get(payload["crops"][crop_idx], payload["crops"][crop_idx])
                field = Field(
                    name=field_code.strip(), company_id=company.id,
                    cluster_id=company.cluster_id, is_active=True,
                    area=float(Decimal(cents) / 100),
                    culture_id=crops[_norm(name)].id,
                )
                db.session.add(field)
                existing[k] = field
                created_fields += 1
            else:
                # A field can belong to one or another cluster in older seasons,
                # but company affiliation must remain structurally coherent.
                if field.cluster_id not in (None, company.cluster_id):
                    raise ValueError("Кластер поля суперечить довіднику підприємства.")
            field_rows.append((field, company, rotations))
        db.session.flush()

        seasonal_rows = []
        source_identities = set()
        created_seasons, updated_seasons = 0, 0
        for field, company, rotations in field_rows:
            for year, cents, crop_idx in rotations:
                season = seasons[year]
                k = (season.id, field.id)
                fs = current_map.get(k)
                if fs is None:
                    fs = FieldSeason(
                        season_id=season.id, field_id=field.id,
                        company_id=company.id, cluster_id=company.cluster_id,
                        area=Decimal(cents) / 100,
                    )
                    db.session.add(fs)
                    created_seasons += 1
                else:
                    fs.company_id = company.id
                    fs.cluster_id = company.cluster_id
                    fs.area = Decimal(cents) / 100
                    updated_seasons += 1
                seasonal_rows.append((fs, cents, crop_idx))
                source_identities.add(k)

        # Obsolete 2020–2026 season links are old test data, not source truth.
        obsolete = [fs for k, fs in current_map.items() if k not in source_identities]
        for fs in obsolete:
            db.session.delete(fs)
        db.session.flush()

        # Replace planting rows only for source-matched historical seasons.
        existing_ids = [fs.id for fs in current if (fs.season_id, fs.field_id) in source_identities]
        if existing_ids:
            db.session.execute(
                delete(FieldPlanting).where(FieldPlanting.field_season_id.in_(existing_ids))
            )
        plantings = []
        for fs, cents, crop_idx in seasonal_rows:
            crop = payload["crops"][crop_idx]
            canonical = CROP_MAPPING.get(crop, crop)
            plantings.append({
                "field_season_id": fs.id,
                "culture_id": crops[_norm(canonical)].id,
                "area": Decimal(cents) / 100,
                "note": "Джерело: Соняшник сторонній" if crop == "Соняшник сторонній" else None,
            })
        db.session.execute(insert(FieldPlanting), plantings)
        db.session.flush()

        # Reconcile every year with the independently checked Google source.
        found = db.session.execute(
            select(Season.year, func.count(FieldSeason.id), func.sum(FieldSeason.area))
            .join(FieldSeason, FieldSeason.season_id == Season.id)
            .where(Season.year >= START_YEAR, Season.year <= END_YEAR)
            .group_by(Season.year)
        ).all()
        measured = {int(year): (int(n), int(Decimal(total) * 100))
                    for year, n, total in found}
        if measured != {int(y): tuple(v) for y, v in expected_stats.items()}:
            raise ValueError("Контрольна сума площ/записів у PostgreSQL не збігається.")
        plantation_count = db.session.execute(
            select(func.count(FieldPlanting.id))
            .select_from(FieldPlanting)
            .join(FieldSeason, FieldPlanting.field_season_id == FieldSeason.id)
            .join(Season, FieldSeason.season_id == Season.id)
            .where(Season.year >= START_YEAR, Season.year <= END_YEAR)
        ).scalar_one()
        expected_total = sum(v[0] for v in expected_stats.values())
        if plantation_count != expected_total:
            raise ValueError("Кількість посівів у БД не збігається з джерелом.")

        db.session.execute(text("""
            INSERT INTO agroerp_history_import_state (name, checksum, imported_rows)
            VALUES (:name, :checksum, :rows)
        """), {"name": STATE_KEY, "checksum": checksum, "rows": expected_total})
        db.session.commit()
        return {
            "skipped": False, "created_fields": created_fields,
            "created_seasonal": created_seasons,
            "updated_seasonal": updated_seasons,
            "removed_legacy_seasonal": len(obsolete),
            "plantings": plantation_count,
            "source_checksum": checksum,
        }
    except Exception:
        db.session.rollback()
        raise


def import_from_environment():
    """Run only on the production service; no data in repo or log output."""
    parts_raw = os.environ.get("AGROERP_FIELD_HISTORY_PARTS")
    checksum = os.environ.get("AGROERP_FIELD_HISTORY_CHECKSUM")
    if not parts_raw or not parts_raw.isdecimal() or not 1 <= int(parts_raw) <= 100:
        raise ValueError("Не налаштовано пакет історії для імпорту.")
    count = int(parts_raw)
    chunks = [os.environ.get(f"AGROERP_FIELD_HISTORY_DATA_{i:03d}") for i in range(count)]
    if any(chunk is None for chunk in chunks) or not checksum:
        raise ValueError("Неповний пакет у змінних Render.")
    return import_history_text("".join(chunks), source_checksum=checksum)
