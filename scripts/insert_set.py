import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — update_set.py lives in scripts/, app/ lives in the project
# root one level up. Run from the project root:
#   python scripts/update_set.py --set swsh12
#   python scripts/update_set.py --set swsh12 --push
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent          # pidex/scripts/
_PROJECT_DIR = _SCRIPTS_DIR.parent            # pidex/

sys.path.insert(0, str(_SCRIPTS_DIR))         # for rarity.py
sys.path.insert(0, str(_PROJECT_DIR))         # for app/

from rarity import normalize_rarity          # noqa: E402

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
PIDEX_DATA_DIR = _PROJECT_DIR.parent / "PiDexData"

IMAGE_DIR      = _PROJECT_DIR / "images"
CARD_IMAGE_DIR = IMAGE_DIR / "cards"
SET_LOGO_DIR   = IMAGE_DIR / "sets" / "logos"
SET_SYMBOL_DIR = IMAGE_DIR / "sets" / "symbols"

SETS_FILE  = PIDEX_DATA_DIR / "sets" / "all.json"
CARDS_DIR  = PIDEX_DATA_DIR / "cards_subset"
PENDING_DIR = _SCRIPTS_DIR / "pending"

# ---------------------------------------------------------------------------
# Pi connection — update these to match your setup
# ---------------------------------------------------------------------------
PI_USER    = "maplemuncher"
PI_HOST    = "pi2-pidex.local"          # or Tailscale IP when off-network
PI_DB_PATH = "~/pidex/instance/pidex.db"
PI_IMG_DIR = "/var/pidex/images/"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_release_date(raw: str | None) -> str | None:
    """Convert '1999/01/09' to '1999-01-09' for SQL."""
    if not raw:
        return None
    return datetime.strptime(raw, "%Y/%m/%d").strftime("%Y-%m-%d")


def _sq(value: str | None) -> str:
    """Wrap a value in single quotes for SQL, escaping internal quotes."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _int_or_null(value) -> str:
    """Return an integer literal or NULL for SQL."""
    if value is None:
        return "NULL"
    try:
        return str(int(value))
    except (ValueError, TypeError):
        return "NULL"


def _download(url: str, dest: Path) -> bool:
    """Download a remote file to dest, skipping if it already exists."""
    import requests
    if dest.exists():
        return True
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
        return True
    except Exception as exc:
        print(f"    [WARN] Could not download {url}: {exc}")
        return False


def _download_all(targets: list[tuple[str, Path]], workers: int = 10) -> None:
    """Download a list of (url, dest) pairs concurrently."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    pending = [(url, dest) for url, dest in targets if not dest.exists()]
    if not pending:
        print("  All images already downloaded, skipping.")
        return
    print(f"  Downloading {len(pending)} images...")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download, url, dest): dest for url, dest in pending}
        for future in as_completed(futures):
            future.result()


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------

def _generate_sql(set_id: str) -> Path:
    """Generate SQL insert file for the given set into scripts/pending/."""

    # Load set metadata
    with open(SETS_FILE) as f:
        sets_data: list[dict] = json.load(f)

    set_meta = next((s for s in sets_data if s["id"] == set_id), None)
    if not set_meta:
        raise ValueError(f"Set '{set_id}' not found in {SETS_FILE}")

    # Load curated card data
    card_file = CARDS_DIR / f"{set_id}.json"
    if not card_file.exists():
        raise FileNotFoundError(
            f"No curated card file found at {card_file}. "
            f"Create PiDexData/cards_subset/{set_id}.json first."
        )

    with open(card_file) as f:
        cards_data: list[dict] = json.load(f)

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
    release_date = _parse_release_date(set_meta.get("releaseDate"))
    lines.append("-- Set")
    lines.append(
        f"INSERT OR IGNORE INTO sets "
        f"(id, code, name, release_date, nr_official_cards, nr_total_cards, series_name, logo_url, symbol_url) VALUES ("
        f"{_sq(set_id)}, "
        f"{_sq(set_meta.get('ptcgoCode', ''))}, "
        f"{_sq(set_meta['name'])}, "
        f"{_sq(release_date)}, "
        f"{_int_or_null(set_meta.get('printedTotal'))}, "
        f"{_int_or_null(set_meta.get('total'))}, "
        f"{_sq(set_meta['series'])}, "
        f"{_sq(set_meta.get('images', {}).get('logo'))}, "
        f"{_sq(set_meta.get('images', {}).get('symbol'))}"
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
            f"{_sq(card_id)}, "
            f"{_sq(entry.get('supertype'))}, "
            f"{_sq(entry['name'])}, "
            f"{_sq(set_id)}, "
            f"{_sq(entry.get('number'))}, "
            f"{_sq(rarity_raw or None)}, "
            f"{_sq(norm.name if norm else None)}, "
            f"{_int_or_null(norm.code if norm else None)}, "
            f"{_sq(img_small)}, "
            f"{_sq(img_large)}, "
            f"{_sq(entry.get('flavorText'))}"
            f");"
        )

        for sub in entry.get("subtypes", []):
            lines.append(
                f"INSERT OR IGNORE INTO card_sub_types (card_id, sub_type) VALUES "
                f"({_sq(card_id)}, {_sq(sub)});"
            )

        for energy in entry.get("types", []):
            lines.append(
                f"INSERT OR IGNORE INTO card_energy_types (card_id, energy_type) VALUES "
                f"({_sq(card_id)}, {_sq(energy)});"
            )

        for dex_num in entry.get("nationalPokedexNumbers", []):
            lines.append(
                f"INSERT OR IGNORE INTO card_pokedex_numbers (card_id, pokedex_number) VALUES "
                f"({_sq(card_id)}, {_int_or_null(dex_num)});"
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

def _download_images(set_id: str) -> None:
    """Download card images and set logo/symbol for the given set."""
    card_file = CARDS_DIR / f"{set_id}.json"
    with open(card_file) as f:
        cards_data: list[dict] = json.load(f)

    with open(SETS_FILE) as f:
        sets_data: list[dict] = json.load(f)
    set_meta = next((s for s in sets_data if s["id"] == set_id), None)

    targets: list[tuple[str, Path]] = []

    # Set logo and symbol
    if set_meta:
        if logo_url := set_meta.get("images", {}).get("logo"):
            targets.append((logo_url, SET_LOGO_DIR / f"{set_id}.png"))
        if symbol_url := set_meta.get("images", {}).get("symbol"):
            targets.append((symbol_url, SET_SYMBOL_DIR / f"{set_id}.png"))

    # Card images (small only)
    for entry in cards_data:
        if img_small := entry.get("images", {}).get("small"):
            raw_number = entry.get("number", entry["id"])
            targets.append((img_small, CARD_IMAGE_DIR / set_id / f"{raw_number}.png"))

    _download_all(targets)
    print(f"  ✓ Images done")


# ---------------------------------------------------------------------------
# Push to Pi
# ---------------------------------------------------------------------------

def _push(set_id: str, sql_file: Path) -> None:
    """Rsync images to Pi and apply SQL over SSH."""
    pi = f"{PI_USER}@{PI_HOST}"
    local_img = str(CARD_IMAGE_DIR / set_id) + "/"
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

    # Apply SQL on Pi
    print("  Applying SQL...")
    apply_cmd = f"sqlite3 {PI_DB_PATH} < ~/pidex/scripts/pending/{set_id}.sql"
    result = subprocess.run(
        ["ssh", pi, f"mkdir -p ~/pidex/scripts/pending && cat > ~/pidex/scripts/pending/{set_id}.sql"],
        input=sql_file.read_bytes(),
        check=False
    )
    if result.returncode != 0:
        print("  [ERROR] Failed to copy SQL file to Pi.")
        return

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

    sql_file = _generate_sql(set_id)
    _download_images(set_id)

    if args.push:
        _push(set_id, sql_file)
    else:
        print(f"\nDone. To push to the Pi, run:")
        print(f"  python scripts/update_set.py --set {set_id} --push")


if __name__ == "__main__":
    main()