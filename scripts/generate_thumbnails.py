"""
One-off script to generate WebP thumbnails for all existing card images.

Run once from the project root after installing Pillow:
    pip install Pillow
    python -m scripts.generate_thumbnails

Thumbnails are saved alongside each image as <number>_thumb.webp.
Already-existing thumbnails are skipped, so the script is safe to re-run.
"""
from pathlib import Path

from scripts.utils import CARD_IMAGE_DIR, THUMB_SIZE, generate_thumbnail


def main() -> None:
    png_files = sorted(CARD_IMAGE_DIR.rglob("*.png"))

    if not png_files:
        print(f"No PNG files found in {CARD_IMAGE_DIR}")
        return

    print(f"Found {len(png_files)} card images. Generating {THUMB_SIZE[0]}×{THUMB_SIZE[1]}px WebP thumbnails...")

    done    = 0
    skipped = 0
    failed  = 0

    for src in png_files:
        dest = src.with_name(src.stem + "_thumb.webp")
        if dest.exists():
            skipped += 1
            continue
        if generate_thumbnail(src, dest):
            done += 1
        else:
            failed += 1

    print(f"\nDone.")
    print(f"  Generated: {done}")
    print(f"  Skipped (already existed): {skipped}")
    print(f"  Failed: {failed}")


if __name__ == "__main__":
    main()