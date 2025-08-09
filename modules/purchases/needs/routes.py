from flask import Blueprint, render_template
from .forms import NeedsFilterForm  # Імпортуємо форму

needs_bp = Blueprint(
    'needs',
    __name__,
    url_prefix='/purchases/needs',
    template_folder='templates'
)

@needs_bp.route('/summary', endpoint='summary')
def summary():
    form = NeedsFilterForm()  # Створюємо форму фільтра
    return render_template('needs/summary.html', form=form)  # Передаємо форму в шаблон
