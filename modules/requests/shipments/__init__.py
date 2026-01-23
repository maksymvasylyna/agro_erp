# modules/requests/shipments/__init__.py
from flask import Blueprint

shipments_requests_bp = Blueprint(
    "shipments_requests",
    __name__,
    template_folder="templates"
)

from . import routes  # noqa: E402,F401
