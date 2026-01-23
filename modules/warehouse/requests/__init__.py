from flask import Blueprint

warehouse_requests_bp = Blueprint(
    "warehouse_requests",
    __name__,
    template_folder="templates"
)

from . import routes  # noqa: E402,F401
