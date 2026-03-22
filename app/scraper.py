"""TCGCollector card scraper.

Fetches and parses a single TCGCollector card page, returning
the card metadata needed to insert it into the local database.
"""
import re

from bs4 import BeautifulSoup
from curl_cffi import requests


def _soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, impersonate="chrome124", timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _by_id(soup, el_id: str) -> str | None:
    el = soup.find(id=el_id)
    return el.get_text(strip=True) if el else None


def _info_label(soup, label: str) -> str | None:
    """Return the text value for a labelled footer item."""
    for div in soup.find_all("div", class_="card-info-footer-item-title"):
        if label in div.get_text(strip=True):
            parent = div.find_parent("div", class_="card-info-footer-item")
            if not parent:
                continue
            text_el = parent.find(["span", "a"], class_="card-info-footer-item-text")
            return text_el.get_text(strip=True) if text_el else None
    return None


def scrape_tcgcollector(url: str) -> dict:
    """Scrape a TCGCollector card page.

    Returns a dict with keys:
        name, super_type, expansion_code, set_number, rarity,
        image_url, pokedex_number (int | None),
        subtypes (list[str]), energy_types (list[str])

    Raises:
        requests.HTTPError  — on a non-2xx HTTP response
        ValueError          — if required fields cannot be found on the page
    """
    soup = _soup(url)

    # Name
    title = soup.find("h1", id="card-info-title")
    name = None
    if title:
        a = title.find("a")
        name = a.get_text(strip=True) if a else None
    if not name:
        raise ValueError("Could not find card name on page.")

    # Super type
    type_el = soup.find(id="card-type-containers")
    super_type = None
    if type_el:
        span = type_el.find("span", class_="card-type-container")
        super_type = span.get_text(strip=True) if span else None

    # Expansion code and card number
    expansion_code = _by_id(soup, "card-info-footer-item-text-expansion-code")
    number_raw = _info_label(soup, "Card number")
    # Card number may be "167/190" or "SWSH167" — keep everything before "/"
    set_number = number_raw.split("/")[0].strip() if number_raw else None

    if not expansion_code or not set_number:
        raise ValueError("Could not determine expansion code or card number.")

    # Rarity
    rarity = _info_label(soup, "Rarity")

    # Image
    img_container = soup.find("div", id="card-image-container")
    image_url = None
    if img_container:
        img = img_container.find("img")
        image_url = img.get("src") if img else None

    # Pokémon-specific fields
    pokedex_number = None
    subtypes = []
    energy_types = []

    if super_type and "Pokémon" in super_type:
        # Stage / subtype
        evo_div = soup.find(id="card-evolution-status")
        if evo_div:
            stage_link = evo_div.find("a")
            if stage_link:
                subtypes = [stage_link.get_text(strip=True)]

        # Energy types
        energy_el = soup.find(id="card-energy-types")
        if energy_el:
            energy_types = [
                img.get("title")
                for img in energy_el.find_all("img", class_="energy-type-symbol")
                if img.get("title")
            ]

        # Pokédex number — field is formatted as "#0136", extract digits only
        dex_raw = _info_label(soup, "Pokédex")
        if dex_raw:
            match = re.search(r"\d+", dex_raw)
            if match:
                pokedex_number = int(match.group())

        print(pokedex_number)

    return {
        "name": name,
        "super_type": super_type,
        "expansion_code": expansion_code,
        "set_number": set_number,
        "rarity": rarity,
        "image_url": image_url,
        "pokedex_number": pokedex_number,
        "subtypes": subtypes,
        "energy_types": energy_types,
    }
