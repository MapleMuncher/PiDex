# Windows
When working with the Pi from Windows, use WSL (Ubuntu) for file transfers.
Open WSL by typing `wsl` in a PowerShell terminal.

`pidex` is an alias in WSL `~/.bashrc` that navigates to the PiDex project directory.

# Transferring the database
Only safe to do before the app is in active use on the Pi. Uses SCP from PowerShell:
```bash
scp instance/pidex.db maplemuncher@[tailscale-ip]:~/pidex/instance/pidex.db
```

# New set pipeline
Run from the PiDex project root:
```bash
python -m scripts.download_set --set swsh12
python -m scripts.curate_set --set swsh12
# Review PiDexData/cards_subset/swsh12.json and adjust manually if needed
python -m scripts.insert_set --set swsh12 --local   # test locally first
python -m scripts.insert_set --set swsh12 --push    # push to Pi when happy
```

`--local` applies the SQL to the local database for inspection.
`--push` rsyncs images and applies the SQL to the Pi over SSH (run from WSL).
The SQL file is always saved to `scripts/pending/` regardless of which flag is used.

# Syncing images manually
Only needed for the initial bulk image transfer, or if images get out of sync.
For new sets, `--push` handles image syncing automatically.
Run from WSL:
```bash
pidex
rsync -av --progress images/ maplemuncher@[tailscale-ip]:/var/pidex/images/
```