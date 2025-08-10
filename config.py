import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key')

    uri = os.environ.get('DATABASE_URL')  # беремо з Render
    if uri and uri.startswith('postgresql://'):
        uri = uri.replace('postgresql://', 'postgresql+psycopg://', 1)

    SQLALCHEMY_DATABASE_URI = uri or (
        'sqlite:///instance/agro_erp.db'
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
