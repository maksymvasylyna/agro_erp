from flask import Blueprint

summary_bp = Blueprint(
    'summary',
    __name__,
    url_prefix='/plans/summary',
    template_folder='templates'
)

from . import routes