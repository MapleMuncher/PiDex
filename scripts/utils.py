"""
Shared utilities for scripts/seed.py and scripts/update_set.py.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent          # pidex/scripts/
_PROJECT_DIR = _SCRIPTS_DIR.parent            # pidex/

PIDEX_DATA_DIR = _PROJECT_DIR.parent / "PiDexData"

IMAGE_DIR      = _PROJECT_DIR / "images"
CARD_IMAGE_DIR = IMAGE_DIR / "cards"
SET_LOGO_DIR   = IMAGE_DIR / "sets" / "logos"
SET_SYMBOL_DIR = IMAGE_DIR / "sets" / "symbols"

SETS_FILE    = PIDEX_DATA_DIR / "sets" / "all.json"
POKEMON_FILE = PIDEX_DATA_DIR / "pokemon" / "subset.json"
CARDS_DIR    = PIDEX_DATA_DIR / "cards_subset"
PENDING_DIR  = _SCRIPTS_DIR / "pending"

# ---------------------------------------------------------------------------
# Image downloading
# ---------------------------------------------------------------------------

def download(url: str, dest: Path) -> bool:
    """Download a remote file to dest, skipping if it already exists.
    Returns True on success."""
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


def download_all(targets: list[tuple[str, Path]], workers: int = 10) -> None:
    """Download a list of (url, dest) pairs concurrently, skipping existing files."""
    pending = [(url, dest) for url, dest in targets if not dest.exists()]
    if not pending:
        return
    print(f"  Downloading {len(pending)} images...")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download, url, dest): dest for url, dest in pending}
        for future in as_completed(futures):
            future.result()  # re-raises any exception from download

# ---------------------------------------------------------------------------
# Image target builders
# ---------------------------------------------------------------------------

def set_image_targets(set_id: str, set_meta: dict) -> list[tuple[str, Path]]:
    """Return (url, dest) pairs for a set's logo and symbol images."""
    targets = []
    if logo_url := set_meta.get("images", {}).get("logo"):
        targets.append((logo_url, SET_LOGO_DIR / f"{set_id}.png"))
    if symbol_url := set_meta.get("images", {}).get("symbol"):
        targets.append((symbol_url, SET_SYMBOL_DIR / f"{set_id}.png"))
    return targets


def card_image_targets(set_id: str, cards_data: list[dict]) -> list[tuple[str, Path]]:
    """Return (url, dest) pairs for all small card images in a set."""
    targets = []
    for entry in cards_data:
        if img_small := entry.get("images", {}).get("small"):
            raw_number = entry.get("number", entry["id"])
            targets.append((img_small, CARD_IMAGE_DIR / set_id / f"{raw_number}.png"))
    return targets


# ---------------------------------------------------------------------------
# SQL helpers (used by update_set.py)
# ---------------------------------------------------------------------------

def sq(value) -> str:
    """Wrap a value in single quotes for SQL, escaping internal quotes."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def int_or_null(value) -> str:
    """Return an integer literal or NULL for SQL."""
    if value is None:
        return "NULL"
    try:
        return str(int(value))
    except (ValueError, TypeError):
        return "NULL"