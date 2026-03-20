from flask import Blueprint, render_template
from sqlalchemy import func, case, distinct

from app import db
from app.models import Card, CardStatus, Set

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    """Render the home dashboard with collection summary stats."""

    total_cards = db.session.scalar(
        db.select(func.count(Card.id))
    ) or 0

    owned_count = db.session.scalar(
        db.select(func.count(CardStatus.card_id))
        .where(CardStatus.owned == True)
    ) or 0

    wanted_only_count = db.session.scalar(
        db.select(func.count(CardStatus.card_id))
        .where(CardStatus.wanted == True, CardStatus.owned != True)
    ) or 0

    total_sets = db.session.scalar(
        db.select(func.count(Set.id))
    ) or 0

    sets_with_cards = db.session.scalar(
        db.select(func.count(distinct(Card.set_code)))
    ) or 0

    return render_template(
        "home/index.html",
        total_cards=total_cards,
        owned_count=owned_count,
        wanted_only_count=wanted_only_count,
        total_sets=total_sets,
        sets_with_cards=sets_with_cards,
    )
