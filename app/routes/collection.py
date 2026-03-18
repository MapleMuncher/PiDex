from flask import Blueprint, render_template, jsonify, request

from app import db
from app.models import Collection

collection_bp = Blueprint("collection", __name__, url_prefix="/collection")


@collection_bp.route("/toggle", methods=["POST"])
def toggle():
    """
    Set the collection status for a card.

    Expects JSON: { "card_id": "base1-1", "status": "WANTED" | "OWNED" | null }

    - "WANTED" or "OWNED" — creates or updates the Collection row
    - null — removes the Collection row (unmarks the card)

    Returns JSON: { "card_id": ..., "status": ... }
    """
    data    = request.get_json()
    card_id = data.get("card_id")
    status  = data.get("status")  # "WANTED", "OWNED", or None

    if not card_id:
        return jsonify({"error": "card_id is required"}), 400

    if status not in ("WANTED", "OWNED", None):
        return jsonify({"error": "status must be WANTED, OWNED, or null"}), 400

    entry = db.session.get(Collection, card_id)

    if status is None:
        # Remove from collection
        if entry:
            db.session.delete(entry)
            db.session.commit()
    elif entry:
        # Update existing entry
        entry.status = status
        db.session.commit()
    else:
        # Create new entry
        entry = Collection(card_id=card_id, status=status, copies_owned=1)
        db.session.add(entry)
        db.session.commit()

    return jsonify({"card_id": card_id, "status": status})


@collection_bp.route("/")
def index():
    """Render the home page."""
    return render_template("collection/index.html")