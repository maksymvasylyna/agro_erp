from flask import Blueprint, render_template
from .forms import NeedsFilterForm

needs_bp = Blueprint(
    'needs',
    __name__,
    url_prefix='/purchases/needs',
    template_folder='templates'
)

@needs_bp.route('/', endpoint='index')
def index():
    form = NeedsFilterForm()
    return render_template('needs/index.html', form=form)

@needs_bp.route('/summary', endpoint='summary')
def summary():
    # Сторінка зведеної потреби
    return render_template('needs/summary.html')
