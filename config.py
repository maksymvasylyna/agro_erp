import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key')

    # Спочатку пробуємо власну змінну, потім стандартну від Render
    uri = os.environ.get('RENDER_DATABASE_URL') or os.environ.get('DATABASE_URL')

    if uri and uri.startswith('postgresql://'):
        uri = uri.replace('postgresql://', 'postgresql+psycopg://', 1)

    SQLALCHEMY_DATABASE_URI = uri or f"sqlite:///{os.path.join(basedir, 'instance', 'agro_erp.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
