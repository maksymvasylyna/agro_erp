from flask import Blueprint, render_template

bp = Blueprint('reference', __name__, template_folder='templates')

@bp.route('/reference')
def index():
    return render_template('reference/index.html')
