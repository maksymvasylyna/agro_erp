from extensions import db

class Category(db.Model):
    __tablename__ = 'categories'  # ✅ Додаєш правильну назву таблиці!

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    def __repr__(self):
        return f"<Category {self.name}>"
