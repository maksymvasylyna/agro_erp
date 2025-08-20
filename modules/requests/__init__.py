from flask import Blueprint

requests_bp = Blueprint(
    "requests",
    __name__,
    template_folder="templates",
)

# ВАЖЛИВО: імпортуємо маршрути, щоб декоратори прикріпилися до blueprint
from . import routes  # noqa: E402,F401
