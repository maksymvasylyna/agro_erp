# modules/plans/routes.py
from flask import Blueprint, render_template

plans_bp = Blueprint('plans', __name__, template_folder='templates')

@plans_bp.route('/')
def hub():
    return render_template('plans/hub.html')



