from flask import Blueprint, render_template

collection_bp = Blueprint("collection", __name__, url_prefix="/collection")


@collection_bp.route("/")
def index():
    """Render the home page."""
    return render_template("collection/index.html")