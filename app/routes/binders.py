from flask import Blueprint, render_template

binders_bp = Blueprint("binders", __name__)


@binders_bp.route("/binders")
def index():
    """Render the home page."""
    return render_template("binders/index.html")