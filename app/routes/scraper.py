import io

from curl_cffi import requests
from flask import Blueprint, flash, redirect, render_template, request, url_for
from PIL import Image

from app import db
from app.models import Card, CardEnergyType, CardPokedexNumber, CardStatus, CardSubType, Set
from app.scraper import scrape_tcgcollector
from scripts.rarity import normalize_rarity
from scripts.utils import CARD_IMAGE_DIR, generate_thumbnail

scraper_bp = Blueprint("scraper", __name__, url_prefix="/import")


def _get_or_create_set(expansion_code: str) -> Set:
    """Return the Set matching expansion_code (by code field), creating a minimal record if absent."""
    s = db.session.execute(
        db.select(Set).where(Set.code == expansion_code)
    ).scalar_one_or_none()
    if s:
        return s

    # Fallback: look up by lowercased expansion code as the set ID
    set_id = expansion_code.lower()
    s = db.session.get(Set, set_id)
    if s:
        return s

    # Create a minimal set record so the FK constraint is satisfied
    s = Set(
        id=set_id,
        code=expansion_code,
        name=expansion_code,
        series_name="Unknown",
    )
    db.session.add(s)
    db.session.flush()
    return s


def _download_image(image_url: str, set_id: str, set_number: str) -> None:
    """Download card image from TCGCollector, save as PNG, and generate thumbnail."""
    try:
        resp = requests.get(image_url, impersonate="chrome124", timeout=15)
        resp.raise_for_status()

        dest_dir = CARD_IMAGE_DIR / set_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{set_number}.png"

        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img.save(dest, "PNG")

        thumb = dest.with_name(f"{set_number}_thumb.webp")
        generate_thumbnail(dest, thumb)
    except Exception as exc:
        print(f"  [WARN] Image download failed for {set_id}/{set_number}: {exc}")


@scraper_bp.route("/", methods=["GET"])
def index():
    cards = db.session.execute(
        db.select(Card)
        .where(Card.manually_added == True)  # noqa: E712
        .join(Set, Card.set_code == Set.id)
        .order_by(Card.id.desc())
    ).scalars().all()
    return render_template("scraper/index.html", cards=cards)


@scraper_bp.route("/", methods=["POST"])
def add():
    url = request.form.get("url", "").strip()
    if not url:
        flash("Please enter a URL.", "warning")
        return redirect(url_for("scraper.index"))

    try:
        data = scrape_tcgcollector(url)
    except Exception as exc:
        flash(f"Scraping failed: {exc}", "danger")
        return redirect(url_for("scraper.index"))

    s = _get_or_create_set(data["expansion_code"])
    card_id = f"{s.id}-{data['set_number']}"

    if db.session.get(Card, card_id):
        flash(f"{data['name']} ({card_id}) is already in the database.", "info")
        return redirect(url_for("scraper.index"))

    rarity_raw = data.get("rarity") or ""
    norm = normalize_rarity(rarity_raw) if rarity_raw else None

    card = Card(
        id=card_id,
        super_type=data.get("super_type"),
        name=data["name"],
        set_code=s.id,
        set_number=data["set_number"],
        rarity=rarity_raw or None,
        norm_rarity=norm.name if norm else None,
        norm_rarity_code=norm.code if norm else None,
        image_url=data.get("image_url"),
        manually_added=True,
    )
    db.session.add(card)

    for sub in data.get("subtypes", []):
        db.session.add(CardSubType(card_id=card_id, sub_type=sub))

    for energy in data.get("energy_types", []):
        db.session.add(CardEnergyType(card_id=card_id, energy_type=energy))

    if dex := data.get("pokedex_number"):
        db.session.add(CardPokedexNumber(card_id=card_id, pokedex_number=dex))

    db.session.commit()

    if data.get("image_url"):
        _download_image(data["image_url"], s.id, data["set_number"])

    flash(f"Added {data['name']} ({card_id}).", "success")
    return redirect(url_for("scraper.index"))


@scraper_bp.route("/<path:card_id>/delete", methods=["POST"])
def delete(card_id: str):
    card = db.session.get(Card, card_id)
    if not card or not card.manually_added:
        flash("Card not found.", "danger")
        return redirect(url_for("scraper.index"))

    name = card.name
    set_id = card.set_code
    number = card.set_number

    db.session.execute(db.delete(CardStatus).where(CardStatus.card_id == card_id))
    db.session.execute(db.delete(CardPokedexNumber).where(CardPokedexNumber.card_id == card_id))
    db.session.execute(db.delete(CardEnergyType).where(CardEnergyType.card_id == card_id))
    db.session.execute(db.delete(CardSubType).where(CardSubType.card_id == card_id))
    db.session.delete(card)
    db.session.commit()

    for suffix in (f"{number}.png", f"{number}_thumb.webp"):
        p = CARD_IMAGE_DIR / set_id / suffix
        if p.exists():
            p.unlink()

    flash(f"Deleted {name}.", "success")
    return redirect(url_for("scraper.index"))
