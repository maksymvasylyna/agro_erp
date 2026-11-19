"""Shared guards for state-changing planning endpoints.

Never trust a template button or a GET URL to authorize mutations.
Every sensitive transition must use POST + CSRF + active-season match.
"""
from flask import abort
from flask_wtf import FlaskForm

from admin_auth import is_admin
from modules.plans.season import validate_posted_season, writable


class PlanActionForm(FlaskForm):
    """CSRF-only form for state-changing planning actions."""
    pass


def verify_plan_action(*, admin=False):
    season = writable()
    validate_posted_season(season)
    if not PlanActionForm().validate_on_submit():
        abort(400, description="Некоректний або застарілий запит. Оновіть сторінку.")
    if admin and not is_admin():
        abort(403, description="Ця дія доступна лише адміністратору.")
    return season
