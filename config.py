import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = 'dev-key'  # Можна замінити на щось надійне у проді
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'instance', 'agro_erp.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
