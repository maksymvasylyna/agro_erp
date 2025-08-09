from flask import Blueprint, render_template

purchases_bp = Blueprint(
    'purchases',
    __name__,
    url_prefix='/purchases',
    template_folder='templates'
)

@purchases_bp.route('/', endpoint='index')
def index():
    # Центральна сторінка блоку "Закупівля"
    return render_template('purchases/index.html')
