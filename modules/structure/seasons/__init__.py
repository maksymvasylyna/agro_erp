"""Seasonal structure blueprint."""
from flask import Blueprint

seasonal_bp = Blueprint("seasonal", __name__, url_prefix="/seasons", template_folder="templates")

from . import routes  # noqa: E402,F401
