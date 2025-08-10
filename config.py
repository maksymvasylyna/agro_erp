import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key')

    # Якщо є DATABASE_URL у змінних середовища (Render) — беремо його
    # Інакше використовуємо локальну SQLite
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(basedir, 'instance', 'agro_erp.db')
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
