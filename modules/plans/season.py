"""One selected harvest season controls all Planning screens and actions."""
from flask import abort, session
from modules.reference.fields.season_models import Season


def context():
    seasons = Season.query.order_by(Season.year.desc()).all()
    chosen = session.get("harvest_year")
    season = next((s for s in seasons if s.year == chosen), None)
    if season is None:
        season = seasons[0] if seasons else None
    if season is not None:
        session["harvest_year"] = season.year
    return {
        "seasons": seasons,
        "season": season,
        "active_year": season.year if season else None,
    }


def current():
    season = context()["season"]
    if season is None:
        abort(409, description="Спочатку створіть сезон у довіднику полів.")
    return season


def writable():
    season = current()
    if season.is_closed:
        abort(409, description="Обраний сезон закритий для редагування.")
    return season


def plan_or_404(plan_id):
    from modules.plans.models import Plan
    return Plan.query.filter_by(id=plan_id, season_id=current().id).first_or_404()


def validate_posted_season(season):
    """An open form for year A must never accidentally write into year B."""
    from flask import request
    raw = request.form.get("season_id")
    if raw is None or raw != str(season.id):
        abort(409, description="Сезон змінився. Оновіть форму і повторіть дію.")
