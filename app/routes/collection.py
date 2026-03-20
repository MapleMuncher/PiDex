from flask import Blueprint, render_template, jsonify, request

from app import db
from app.models import CardStatus

collection_bp = Blueprint("collection", __name__, url_prefix="/collection")


@collection_bp.route("/toggle", methods=["POST"])
def toggle():
    """
    Set the owned/wanted status for a card.

    Expects JSON: { "card_id": "base1-1", "owned": true/false, "wanted": true/false }

    - Creates or updates the CardStatus row
    - Deletes the row if both owned and wanted are false

    Returns JSON: { "card_id": ..., "owned": ..., "wanted": ... }
    """
    data    = request.get_json()
    card_id = data.get("card_id")
    owned   = bool(data.get("owned", False))
    wanted  = bool(data.get("wanted", False))

    if not card_id:
        return jsonify({"error": "card_id is required"}), 400

    entry = db.session.get(CardStatus, card_id)

    if not owned and not wanted:
        # Remove from card_status
        if entry:
            db.session.delete(entry)
            db.session.commit()
    elif entry:
        # Update existing entry
        entry.owned = owned
        entry.wanted = wanted
        db.session.commit()
    else:
        # Create new entry
        entry = CardStatus(card_id=card_id, owned=owned, wanted=wanted)
        db.session.add(entry)
        db.session.commit()

    return jsonify({"card_id": card_id, "owned": owned, "wanted": wanted})


@collection_bp.route("/")
def index():
    """Render the home page."""
    return render_template("collection/index.html")
