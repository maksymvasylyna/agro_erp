import os
import sys
from sqlalchemy import text, inspect

# --- зробити видимим корінь проєкту для імпортів ---
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # ../
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# --- імпорти вже після додання BASE_DIR ---
from app import create_app          # у тебе є create_app() в app.py
from extensions import db

TABLE = "stock_transactions"

# колонки, які додамо якщо відсутні
COLUMNS = {
    "source_line_idx": "INTEGER",
    "product_name": "TEXT",
    "unit_text": "TEXT",
    "consumer_company_name": "TEXT",
    "payer_name": "TEXT",
    "package_text": "TEXT",
    "manufacturer_name": "TEXT",
}

def main():
    app = create_app()
    with app.app_context():
        insp = inspect(db.engine)
        existing = {c["name"] for c in insp.get_columns(TABLE)}
        added = []
        for name, coltype in COLUMNS.items():
            if name not in existing:
                db.session.execute(text(f'ALTER TABLE {TABLE} ADD COLUMN {name} {coltype}'))
                added.append(name)
        db.session.commit()
        print(f"Done. Added columns: {added or 'none (already up-to-date)'}")

if __name__ == "__main__":
    main()
