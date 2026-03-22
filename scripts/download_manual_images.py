"""
One-off script to download images and generate thumbnails for all manually
imported cards (cards added via the TCGCollector scraper).

Run from the project root:
    python -m scripts.download_manual_images
"""
import io

from PIL import Image
from curl_cffi import requests

from app import create_app, db
from app.models import Card
from scripts.utils import CARD_IMAGE_DIR, generate_thumbnail

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def main() -> None:
    app = create_app()
    with app.app_context():
        cards = db.session.execute(
            db.select(Card).where(Card.manually_added == True)  # noqa: E712
        ).scalars().all()

    if not cards:
        print("No manually imported cards found.")
        return

    print(f"Found {len(cards)} manually imported card(s).")

    done = 0
    skipped = 0
    failed = 0

    for card in cards:
        dest = CARD_IMAGE_DIR / card.set_code / f"{card.set_number}.png"
        thumb = dest.with_name(f"{card.set_number}_thumb.webp")

        if dest.exists() and thumb.exists():
            skipped += 1
            continue

        if not card.image_url:
            print(f"  [SKIP] {card.name} ({card.id}) — no image URL stored.")
            skipped += 1
            continue

        print(f"  Downloading {card.name} ({card.id})...")
        try:
            resp = requests.get(card.image_url, impersonate="chrome124", timeout=15)
            resp.raise_for_status()

            dest.parent.mkdir(parents=True, exist_ok=True)
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            img.save(dest, "PNG")

            generate_thumbnail(dest, thumb)
            print(f"    ✓ Saved image and thumbnail.")
            done += 1
        except Exception as exc:
            print(f"    [ERROR] {exc}")
            failed += 1

    print(f"\nDone. Downloaded: {done}, Skipped: {skipped}, Failed: {failed}")


if __name__ == "__main__":
    main()
