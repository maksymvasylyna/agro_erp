from flask import Blueprint

warehouse_bp = Blueprint(
    "warehouse",
    __name__,
    template_folder="templates",
    url_prefix="/warehouse"
)

from . import routes  # noqa: F401
