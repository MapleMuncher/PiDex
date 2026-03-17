import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from scripts.rarity import normalize_rarity
from scripts.utils import (
    CARD_IMAGE_DIR, CARDS_DIR, PENDING_DIR, SETS_FILE,
    card_image_targets, download_all, int_or_null,
    set_image_targets, sq,
)

# ---------------------------------------------------------------------------
# Pi connection — update these to match your setup
# ---------------------------------------------------------------------------
PI_USER    = "maplemuncher"
PI_HOST    = "pi2-pidex.local"          # or Tailscale IP when off-network
PI_DB_PATH = "~/pidex/instance/pidex.db"
PI_IMG_DIR = "/var/pidex/images/"


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------

def _generate_sql(set_id: str, set_meta: dict, cards_data: list[dict]) -> Path:
    """Generate SQL insert file for the given set into scripts/pending/."""
    PENDING_DIR.mkdir(exist_ok=True)
    sql_file = PENDING_DIR / f"{set_id}.sql"

    lines: list[str] = []
    lines.append(f"-- Update script for set: {set_id}")
    lines.append(f"-- Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"-- Cards: {len(cards_data)}")
    lines.append("")
    lines.append("BEGIN TRANSACTION;")
    lines.append("")

    # Insert set row
    release_date = None
    if raw_date := set_meta.get("releaseDate"):
        release_date = datetime.strptime(raw_date, "%Y/%m/%d").strftime("%Y-%m-%d")

    lines.append("-- Set")
    lines.append(
        f"INSERT OR IGNORE INTO sets "
        f"(id, code, name, release_date, nr_official_cards, nr_total_cards, series_name, logo_url, symbol_url) VALUES ("
        f"{sq(set_id)}, "
        f"{sq(set_meta.get('ptcgoCode', ''))}, "
        f"{sq(set_meta['name'])}, "
        f"{sq(release_date)}, "
        f"{int_or_null(set_meta.get('printedTotal'))}, "
        f"{int_or_null(set_meta.get('total'))}, "
        f"{sq(set_meta['series'])}, "
        f"{sq(set_meta.get('images', {}).get('logo'))}, "
        f"{sq(set_meta.get('images', {}).get('symbol'))}"
        f");"
    )
    lines.append("")

    # Insert cards and related rows
    lines.append("-- Cards")
    for entry in cards_data:
        card_id    = entry["id"]
        rarity_raw = entry.get("rarity") or ""
        norm       = normalize_rarity(rarity_raw) if rarity_raw else None
        img_small  = entry.get("images", {}).get("small")
        img_large  = entry.get("images", {}).get("large")

        lines.append(
            f"INSERT OR IGNORE INTO cards "
            f"(id, super_type, name, set_code, set_number, rarity, norm_rarity, norm_rarity_code, image_url, hd_image_url, flavor) VALUES ("
            f"{sq(card_id)}, "
            f"{sq(entry.get('supertype'))}, "
            f"{sq(entry['name'])}, "
            f"{sq(set_id)}, "
            f"{sq(entry.get('number'))}, "
            f"{sq(rarity_raw or None)}, "
            f"{sq(norm.name if norm else None)}, "
            f"{int_or_null(norm.code if norm else None)}, "
            f"{sq(img_small)}, "
            f"{sq(img_large)}, "
            f"{sq(entry.get('flavorText'))}"
            f");"
        )

        for sub in entry.get("subtypes", []):
            lines.append(
                f"INSERT OR IGNORE INTO card_sub_types (card_id, sub_type) VALUES "
                f"({sq(card_id)}, {sq(sub)});"
            )

        for energy in entry.get("types", []):
            lines.append(
                f"INSERT OR IGNORE INTO card_energy_types (card_id, energy_type) VALUES "
                f"({sq(card_id)}, {sq(energy)});"
            )

        for dex_num in entry.get("nationalPokedexNumbers", []):
            lines.append(
                f"INSERT OR IGNORE INTO card_pokedex_numbers (card_id, pokedex_number) VALUES "
                f"({sq(card_id)}, {int_or_null(dex_num)});"
            )

        lines.append("")

    lines.append("COMMIT;")
    lines.append("")

    sql_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✓ SQL written to {sql_file} ({len(cards_data)} cards)")
    return sql_file


# ---------------------------------------------------------------------------
# Image downloading
# ---------------------------------------------------------------------------

def _download_images(set_id: str, set_meta: dict, cards_data: list[dict]) -> None:
    """Download card images and set logo/symbol for the given set."""
    targets = set_image_targets(set_id, set_meta) + card_image_targets(set_id, cards_data)
    download_all(targets)
    print("  ✓ Images done")


# ---------------------------------------------------------------------------
# Push to Pi
# ---------------------------------------------------------------------------

def _push(set_id: str, sql_file: Path) -> None:
    """Rsync images to Pi and apply SQL over SSH."""
    pi = f"{PI_USER}@{PI_HOST}"
    local_img  = str(CARD_IMAGE_DIR / set_id) + "/"
    remote_img = f"{PI_IMG_DIR}cards/{set_id}/"

    print(f"\nPushing to {PI_HOST}...")

    # Rsync card images
    print("  Syncing images...")
    result = subprocess.run(
        ["rsync", "-av", "--progress", local_img, f"{pi}:{remote_img}"],
        check=False
    )
    if result.returncode != 0:
        print("  [ERROR] rsync failed. Aborting push.")
        return

    # Stream SQL file to Pi and apply it
    print("  Applying SQL...")
    copy_cmd = f"mkdir -p ~/pidex/scripts/pending && cat > ~/pidex/scripts/pending/{set_id}.sql"
    result = subprocess.run(
        ["ssh", pi, copy_cmd],
        input=sql_file.read_bytes(),
        check=False
    )
    if result.returncode != 0:
        print("  [ERROR] Failed to copy SQL file to Pi.")
        return

    apply_cmd = f"sqlite3 {PI_DB_PATH} < ~/pidex/scripts/pending/{set_id}.sql"
    result = subprocess.run(["ssh", pi, apply_cmd], check=False)
    if result.returncode != 0:
        print("  [ERROR] Failed to apply SQL on Pi.")
        return

    print(f"  ✓ Set {set_id} pushed and applied successfully.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate SQL and download images for a new Pokémon TCG set."
    )
    parser.add_argument(
        "--set", required=True, metavar="SET_ID",
        help="Set code to process, e.g. swsh12"
    )
    parser.add_argument(
        "--push", action="store_true",
        help="After generating SQL and downloading images, push to the Pi."
    )
    args = parser.parse_args()
    set_id = args.set

    print(f"Processing set: {set_id}")

    # Load data once and pass it through to avoid reading files twice
    with open(SETS_FILE) as f:
        sets_data: list[dict] = json.load(f)
    set_meta = next((s for s in sets_data if s["id"] == set_id), None)
    if not set_meta:
        raise ValueError(f"Set '{set_id}' not found in {SETS_FILE}")

    card_file = CARDS_DIR / f"{set_id}.json"
    if not card_file.exists():
        print(f"  [ERROR] No curated card file found at {card_file}.")
        print(f"  Run: python -m scripts.curate_set --set {set_id}")
        sys.exit(1)

    with open(card_file) as f:
        cards_data: list[dict] = json.load(f)

    sql_file = _generate_sql(set_id, set_meta, cards_data)
    _download_images(set_id, set_meta, cards_data)

    if args.push:
        _push(set_id, sql_file)
    else:
        print(f"\nDone. To push to the Pi, run:")
        print(f"  python -m scripts.insert_set --set {set_id} --push")


if __name__ == "__main__":
    main()