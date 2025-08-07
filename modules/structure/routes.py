from flask import Blueprint, render_template

structure_bp = Blueprint(
    'structure',
    __name__,
    template_folder='templates'
)

@structure_bp.route('/structure')
def index():
    return render_template('structure/index.html')
