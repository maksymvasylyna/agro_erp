from extensions import db
from modules.reference.fields.field_models import Field

# ✅ Імпорт твого factory!
from app import create_app

app = create_app()  # ✅ Тепер Flask app існує

with app.app_context():
    print("⚡ Dropping 'fields' table...")
    Field.__table__.drop(db.engine)
    print("✅ Dropped.")

    print("⚡ Creating 'fields' table...")
    Field.__table__.create(db.engine)
    print("✅ Created with new columns!")

    # Перевіримо, що колонка є
    insp = db.inspect(db.engine)
    columns = insp.get_columns('fields')
    print("🗂️ Columns in 'fields':")
    for col in columns:
        print(f"- {col['name']} ({col['type']})")
