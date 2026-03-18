from flask import Blueprint, render_template

sets_bp = Blueprint("sets", __name__)


@sets_bp.route("/sets")
def index():
    """Render the home page."""
    return render_template("sets/index.html")