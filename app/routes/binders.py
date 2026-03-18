from flask import Blueprint, render_template

binders_bp = Blueprint("binders", __name__, url_prefix="/binders")


@binders_bp.route("/")
def index():
    """Render the home page."""
    return render_template("binders/index.html")