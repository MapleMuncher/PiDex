# Inserting a new set of cards
From the PiDex root run the following commands:

```bash
python scripts/download_set.py --set swsh12
python scripts/curate_set.py --set swsh12
# Review PiDexData/cards_subset/swsh12.json
python scripts/insert_set.py --set swsh12 --push
```