from flask import render_template
from . import requests_bp

@requests_bp.route("/", endpoint="index")
def index():
    return render_template(
        "requests/index.html",
        title="Заявки",
        header="Заявки",
    )
