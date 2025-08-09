# scripts/reset_all.py

from extensions import db
from app import create_app

app = create_app()

# 🗝️ ІМПОРТУЙ УСІ МОДЕЛІ!
from modules.reference.clusters.models import Cluster
from modules.reference.companies.models import Company
from modules.reference.cultures.models import Culture  # 🟢 Ось ця — ключ!
from modules.reference.fields.field_models import Field
# Додай інші, якщо є ForeignKey

with app.app_context():
    print("⚡ Dropping ALL tables...")
    db.drop_all()
    print("✅ Dropped.")

    print("⚡ Creating ALL tables...")
    db.create_all()
    print("✅ Created all tables with all ForeignKey constraints!")

    insp = db.inspect(db.engine)
    columns = insp.get_columns('fields')
    print("🗂️ Columns in 'fields':")
    for col in columns:
        print(f"- {col['name']} ({col['type']})")
