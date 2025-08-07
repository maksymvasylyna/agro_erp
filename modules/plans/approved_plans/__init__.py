from flask import Blueprint

bp = Blueprint('approved_plans', __name__, template_folder='templates')

from . import routes  # 👈 обовʼязково, щоб підключились всі маршрути
