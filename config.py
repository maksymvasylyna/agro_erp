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

    # The free staging PostgreSQL can drop TLS sessions unexpectedly. Avoid
    # reusing disconnected libpq connections across Flask/Gunicorn requests.
    # NullPool opens one connection per request/transaction and closes it when
    # Flask-SQLAlchemy releases the session. Keep production untouched.
    if os.environ.get("AGROERP_ENV") == "staging" and SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
        from sqlalchemy.pool import NullPool
        SQLALCHEMY_ENGINE_OPTIONS = {
            "poolclass": NullPool,
            "connect_args": {"connect_timeout": 10},
        }

