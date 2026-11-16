"""One-time verified reference sync for historical field data (2020-2026).

Source: Google Sheet 'Основний файл даних про поля', tab 'Історія полів'.
Cluster mapping: existing AgroERP test PostgreSQL (16 historical companies);
the 2020-only Agrokontrakt project is assigned to Cluster 1 separately.

Never imports field rows, overwrites fields, deletes dictionaries, or merges
distinct historical enterprises. Run once via AGROERP_SYNC_FIELD_REFS_2020_2026.
"""
from extensions import db
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture
from modules.reference.fields.season_models import Season

# Existing production names are aliases: preserve IDs and all foreign keys.
# canonical name, cluster, known old production names
COMPANIES = (
    ("Агро-Центр ФГ", "Кластер 1", ()),
    ("Агроконтракт-Н 2021 ТОВ", "Кластер 1", ("ТОВ Агроконтракт",)),
    ("Агроконтракт-Н(проект) ТОВ", "Кластер 1", ()),
    ("АЙ ЕНД Ю ГРУП АГРО ПП", "Кластер 1", ("Ай Енд Ю Груп Агро",)),
    ("Баланс-Агро ФГ", "Кластер 1", ()),
    ("КОЛОСАГРОТЕХ-ТРК ТОВ", "Кластер 1", ()),
    ("Мега -Тренд ТОВ", "Кластер 1", ()),
    ("Оситнянське ТОВ", "Кластер 1", ()),
    ("Перлина ПП", "Кластер 1", ()),
    ("Тясмин СТОВ", "Кластер 1", ("СТОВ Тясмин",)),
    ("Митрофанівська ПП", "Кластер 2", ("ПП АФ Митрофанівська",)),
    ("Перспектива ПП", "Кластер 2", ("ПП АФ Перспектива",)),
    ("Престиж ПП", "Кластер 2", ("ПП АФ Престиж",)),
    ("Агро-Прім ТОВ", "Кластер 3", ("ТОВ Агро-Прім",)),
    ("АФ ім. Чкалова ТОВ", "Кластер 3", ("ТОВ АФ ім. Чкалова",)),
    ("Горизонт ТОВ", "Кластер 3", ("ТОВ Горизонт",)),
    ("Миколаївське ПрАТ", "Миколаївське", ()),
)
# Seven missing crops in the 2020-2026 period. Existing "Кукурудза на зерно"
# represents source "Кукурудза"; "Соняшник сторонній" is a crop note, not
# a standalone botanical crop. The 2027 winter pea is deliberately excluded.
MISSING_CULTURES = (
    "Буряк цукровий", "Пар", "Соя", "Сорго цукрове",
    "Ячмінь ярий", "Жито озиме на силос", "Пшениця яра",
)
MISSING_YEARS = tuple(range(2020, 2026))
CLUSTER_ALIASES = {"Миколаївське": ("ТОВ ПрАТ Миколаївське",)}
EXPECTED_CLUSTERS = ("Кластер 1", "Кластер 2", "Кластер 3", "Миколаївське")


def _key(value):
    return " ".join((value or "").split()).casefold()


def build_reference_plan():
    """Inspect existing dictionaries and fail closed on ambiguous matches.

    Returns a plan with SQLAlchemy objects for UPDATE and pure data for INSERT.
    Does NOT touch the session or database.
    """
    existing_clusters = Cluster.query.all()
    existing_companies = Company.query.all()
    existing_cultures = Culture.query.all()
    existing_seasons = Season.query.all()
    plan = {"cluster_renames": [], "company_renames": [],
            "company_additions": [], "culture_additions": [],
            "season_additions": [], "present_companies": []}
    cluster_map = {}
    for canonical in EXPECTED_CLUSTERS:
        keys = {_key(canonical), *(_key(a) for a in CLUSTER_ALIASES.get(canonical, ()))}
        found = [cluster for cluster in existing_clusters if _key(cluster.name) in keys]
        if len(found) != 1:
            raise ValueError(
                f"Очікувався один наявний кластер «{canonical}», знайдено {len(found)}. "
                "Додавання призупинене, щоб не створити помилкових прив'язок."
            )
        cluster_map[canonical] = found[0]
        if found[0].name != canonical:
            plan["cluster_renames"].append((found[0], canonical))

    already_matched = set()
    for canonical, cluster_name, aliases in COMPANIES:
        keys = {_key(canonical), *(_key(x) for x in aliases)}
        candidates = [c for c in existing_companies if _key(c.name) in keys]
        if len(candidates) > 1:
            raise ValueError(f"Дублікати підприємства {canonical}: збереження зупинено.")
        cluster = cluster_map[cluster_name]
        if candidates:
            company = candidates[0]
            if company.id in already_matched:
                raise ValueError(f"Неоднозначне зіставлення підприємства {canonical}")
            already_matched.add(company.id)
            if company.cluster_id != cluster.id:
                raise ValueError(f"Невідповідний кластер підприємства {canonical}; зміни зупинено.")
            plan["present_companies"].append(canonical)
            if company.name != canonical:
                plan["company_renames"].append((company, canonical))
        else:
            plan["company_additions"].append((canonical, cluster.id))

    culture_keys = [_key(c.name) for c in existing_cultures]
    for crop in MISSING_CULTURES:
        if _key(crop) not in culture_keys:
            plan["culture_additions"].append(crop)
    year_set = {season.year for season in existing_seasons}
    for year in MISSING_YEARS:
        if year not in year_set:
            plan["season_additions"].append(year)
    return plan


def sync_reference_dictionaries(*, dry_run=True):
    """Apply a single atomic, idempotent catalog update when dry_run=False."""
    plan = build_reference_plan()
    report = {
        "cluster_renames": [(obj.name, name) for obj, name in plan["cluster_renames"]],
        "company_renames": [(obj.name, name) for obj, name in plan["company_renames"]],
        "company_additions": [name for name, _ in plan["company_additions"]],
        "culture_additions": list(plan["culture_additions"]),
        "season_additions": list(plan["season_additions"]),
        "existing_companies": len(plan["present_companies"]),
        "dry_run": dry_run,
    }
    if dry_run:
        return report
    try:
        for cluster, new_name in plan["cluster_renames"]:
            cluster.name = new_name
        for company, new_name in plan["company_renames"]:
            company.name = new_name
        for name, cluster_id in plan["company_additions"]:
            db.session.add(Company(name=name, cluster_id=cluster_id))
        for name in plan["culture_additions"]:
            db.session.add(Culture(name=name))
        for year in plan["season_additions"]:
            db.session.add(Season(year=year, is_closed=False))
        db.session.flush()
        # Ensure all intended companies exist with correct clusters.
        if len(plan["present_companies"]) + len(plan["company_additions"]) != len(COMPANIES):
            raise ValueError("Помилка повноти списку підприємств.")
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return report
