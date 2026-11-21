# Mister Tidy

Mister Tidy puts console launchers directly in the MiSTer boot menu.

## Install

**Back up your SD card first.** The installer deletes files outside the allowlists before updating. If the update fails, those files are already gone.

Copy `mister-tidy.sh` to the SD card’s `scripts/` folder and run it from the MiSTer Scripts menu. It targets `/media/fat` by default. Pass a card path to target another directory.

The installer normalizes folder names, installs the helpers, updates the card, and builds the game cache. It removes itself after a successful run.

## Final SD-card layout

```text
/
├── MiSTer
├── menu.rbf
├── MiSTer*.ini
├── NES_<date>.rbf
├── SNES_<date>.rbf
├── config/
├── games/
├── linux/
├── saves/
├── savestates/
└── scripts/
```

The two core files are examples. See the [layout specification](SPEC.md) for the full rules.

## Helper scripts

| Script | Action |
| --- | --- |
| `clean.sh` | Normalize names and prune the card |
| `update.sh` | Sync cores, game data, BIOS files, and helpers |
| `cache.sh` | Build the random-game cache |
| `random.sh` | Launch a random cached game |
| `last.sh` | Relaunch the last generated selection |
| `delete.sh` | Delete the selected game and clear its launch file |
