# Inserting a new set of cards
From the PiDex root run the following commands:

```bash
python -m scripts.download_set --set swsh12
python -m scripts.curate_set --set swsh12
python -m scripts.insert_set --set swsh12 --push
```