from flask import Blueprint, render_template

collection_bp = Blueprint("collection", __name__)


@collection_bp.route("/collection")
def index():
    """Render the home page."""
    return render_template("collection/index.html")