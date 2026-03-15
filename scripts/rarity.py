import re
from dataclasses import dataclass, field

@dataclass
class Rarity:
    name: str
    code: int

@dataclass
class RarityMapper:
    rarity: Rarity
    kw_sets: list[set[str]] = field(default_factory=list)

_RULE_BOX_NAMES = {'ex', 'gx', 'v', 'vmax', 'vstar', 'lv'}

_RARITY_MAPPERS: list[RarityMapper] = [
    RarityMapper(Rarity('Special', 10), [
        {'legend'},
        {'break'},
        {'amazing', 'rare'},
        {'prism', 'rare'},          # Prism Star
        {'radiant', 'rare'},
        {'ace', 'rare'},            # ACE Spec
        {'mega', 'rare'},
        {'prime', 'rare'},
        {'rare', 'star'},           # Gold Star
        {'classic', 'collection'}
    ]),
    RarityMapper(Rarity('Secret', 9), [
        {'secret', 'rare'},
        {'ultra', 'rare'},
        {'hyper', 'rare'},
        {'rainbow', 'rare'},
        {'black', 'white', 'rare'}
    ]),
    RarityMapper(Rarity('Shiny', 8), [
        {'shiny', 'rare'},
        {'shining', 'rare'}
    ]),
    RarityMapper(Rarity('Illustration', 7), [
        {'illustration', 'rare'},
        {'trainer', 'gallery'},
    ]),
    RarityMapper(Rarity('Double Rare', 6), [
        {'double', 'rare'},
        *[{'holo', 'rare', rule_box} for rule_box in _RULE_BOX_NAMES]
    ]),
    RarityMapper(Rarity('Promo', 5), [{'promo'}]),
    RarityMapper(Rarity('Holo Rare', 4), [{'holo', 'rare'}]),
    RarityMapper(Rarity('Rare', 3), [{'rare'}]),
    RarityMapper(Rarity('Uncommon', 2), [{'uncommon'}]),
    RarityMapper(Rarity('Common', 1), [{'common'}])
]

def normalize_rarity(rarity: str) -> Rarity:
    clean_rarity = rarity.replace('_', ' ').lower()
    
    # Get a list of all words in the rarity string
    rarity_words = set(re.findall(r'\b\w+\b', clean_rarity))

    for mapper in _RARITY_MAPPERS:
        if any(kw_set.issubset(rarity_words) for kw_set in mapper.kw_sets):
            return mapper.rarity

    # If no matching rule is found, return the original rarity
    return Rarity(rarity, 99)