# reset_db.py

from app import create_app
from extensions import db

app = create_app()

with app.app_context():
    print("⚠️ Всі таблиці будуть видалені...")
    db.drop_all()
    print("🧹 Таблиці видалено.")
    db.create_all()
    print("✅ Базу даних створено заново.")
