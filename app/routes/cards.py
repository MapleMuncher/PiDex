from flask import Blueprint, render_template

cards_bp = Blueprint("cards", __name__)


@cards_bp.route("/")
def index():
    """Render the home page."""
    return render_template("cards/index.html")