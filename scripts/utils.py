"""
Shared utilities for seed.py, curate_set.py, and insert_set.py.
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent          # pidex/scripts/
_PROJECT_DIR = _SCRIPTS_DIR.parent            # pidex/

# Override with PIDEX_DATA env var if set; defaults to a sibling PiDexData/
PIDEX_DATA_DIR = Path(os.environ.get("PIDEX_DATA", _PROJECT_DIR.parent / "PiDexData"))

IMAGE_DIR      = _PROJECT_DIR / "images"
CARD_IMAGE_DIR = IMAGE_DIR / "cards"
SET_LOGO_DIR   = IMAGE_DIR / "sets" / "logos"
SET_SYMBOL_DIR = IMAGE_DIR / "sets" / "symbols"

SETS_FILE    = PIDEX_DATA_DIR / "sets" / "all.json"
POKEMON_FILE = PIDEX_DATA_DIR / "pokemon" / "subset.json"
CARDS_DIR    = PIDEX_DATA_DIR / "cards_subset"
RAW_CARDS_DIR = PIDEX_DATA_DIR / "cards"
PENDING_DIR  = _SCRIPTS_DIR / "pending"

# ---------------------------------------------------------------------------
# Thumbnail settings
# ---------------------------------------------------------------------------
THUMB_SIZE    = (150, 210)   # width × height in pixels
THUMB_SUFFIX  = "_thumb.webp"

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

# Normalised rarities allowed through the rarity filter
ALLOWED_RARITIES = {"Common", "Uncommon", "Rare", "Double Rare", "Holo Rare"}

# Pokédex numbers allowed through the Pokédex filter
_POKEDEX_FILTER: set[int] = (
    set(range(1, 252))       # Gen 1 & 2
    | set(range(252, 255))   # Treecko, Grovyle, Sceptile
    | set(range(273, 276))   # Seedot, Nuzleaf, Shiftry
    | set(range(280, 283))   # Ralts, Kirlia, Gardevoir
    | {285, 286}             # Shroomish, Breloom
    | set(range(304, 307))   # Aron, Lairon, Aggron
    | {307, 308}             # Meditite, Medicham
    | set(range(328, 331))   # Trapinch, Vibrava, Flygon
    | {335}                  # Zangoose
    | {349, 350}             # Feebas, Milotic
    | {359}                  # Absol
    | set(range(363, 366))   # Spheal, Sealeo, Walrein
    | set(range(371, 374))   # Bagon, Shelgon, Salamence
    | set(range(374, 377))   # Beldum, Metang, Metagross
    | set(range(377, 385))   # Gen 3 legendaries
    | set(range(403, 406))   # Shinx, Luxio, Luxray
    | {447, 448}             # Riolu, Lucario
    | {461}                  # Weavile
    | {475}                  # Gallade
)


def passes_rarity_filter(norm_rarity: str | None) -> bool:
    """Return True if the normalised rarity is in the allowed set."""
    return norm_rarity in ALLOWED_RARITIES


def passes_pokedex_filter(pokedex_numbers: list[int]) -> bool:
    """Return True if at least one Pokédex number is in the allowed set."""
    return any(n in _POKEDEX_FILTER for n in pokedex_numbers)


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
            future.result()


# ---------------------------------------------------------------------------
# Thumbnail generation
# ---------------------------------------------------------------------------

def generate_thumbnail(src: Path, dest: Path | None = None) -> bool:
    """
    Generate a WebP thumbnail from a source image file.

    The thumbnail is saved at THUMB_SIZE (150×210px) using high-quality
    Lanczos resampling. If dest is not provided, the thumbnail is saved
    alongside the source with a _thumb.webp suffix.

    Skips generation if the thumbnail already exists.
    Returns True on success, False on failure.
    """
    from PIL import Image

    if dest is None:
        dest = src.with_name(src.stem + THUMB_SUFFIX)

    if dest.exists():
        return True

    try:
        with Image.open(src) as img:
            img = img.convert("RGBA")
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest, "WEBP", quality=85)
        return True
    except Exception as exc:
        print(f"    [WARN] Could not generate thumbnail for {src}: {exc}")
        return False


def generate_thumbnails_all(
    targets: list[tuple[Path, Path | None]],
    workers: int = 8,
) -> None:
    """
    Generate thumbnails for a list of (src, dest) pairs concurrently.
    Pass dest=None to use the default _thumb.webp naming alongside src.
    Skips any thumbnail that already exists.
    """
    pending = [
        (src, dest) for src, dest in targets
        if src.exists() and not (dest or src.with_name(src.stem + THUMB_SUFFIX)).exists()
    ]
    if not pending:
        return
    print(f"  Generating {len(pending)} thumbnails...")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(generate_thumbnail, src, dest): src
            for src, dest in pending
        }
        for future in as_completed(futures):
            future.result()


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


def card_thumbnail_targets(set_id: str, cards_data: list[dict]) -> list[tuple[Path, None]]:
    """Return (src, None) pairs for thumbnail generation for all cards in a set."""
    targets = []
    for entry in cards_data:
        raw_number = entry.get("number", entry["id"])
        src = CARD_IMAGE_DIR / set_id / f"{raw_number}.png"
        targets.append((src, None))
    return targets


# ---------------------------------------------------------------------------
# SQL helpers (used by insert_set.py)
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