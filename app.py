import sys
import os
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from flask import Flask, render_template
from config import Config
from extensions import db
from register_blueprints import register_blueprints

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    register_blueprints(app)

    # ✅ ОБОВʼЯЗКОВО: імпортуємо всі моделі, які мають зв’язки
    from modules.reference.products.models import Product
    from modules.reference.categories.models import Category
    from modules.reference.units.models import Unit
    from modules.reference.groups.models import Group
    from modules.reference.manufacturers.models import Manufacturer
    from modules.reference.payers.models import Payer
    from modules.reference.currencies.models import Currency
    from modules.reference.clusters.models import Cluster
    from modules.reference.cultures.models import Culture
    from modules.reference.companies.models import Company
    from modules.reference.fields.models import Field
    # Додай сюди інші моделі, якщо є ForeignKey

    with app.app_context():
        db.create_all()  # створює всі таблиці, бо тепер знає про них!

    @app.route('/')
    def index():
        return render_template('index.html')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5001, debug=True)
