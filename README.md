# Mister Tidy

Mister Tidy puts console launchers directly in the MiSTer boot menu.

## Install

**Back up your SD card first.** Every update deletes files outside the allowlists below, including anything you add later.

Copy `scripts/update.sh` to the SD card’s `scripts/` folder and run it from the MiSTer Scripts menu. It installs the other scripts and keeps itself up to date. It targets `/media/fat` by default; pass a card path to target another directory.

## Scripts menu

| Script | Action |
| --- | --- |
| `update.sh` | Update the card and refresh the game cache |
| `shuffle.sh` | Launch a random game without repeating a pick until the pool is exhausted |
| `repeat.sh` | Relaunch the last selection |
| `delete.sh` | Delete the selected game and clear its launch file |

## Card layout

```text
/
├── MiSTer
├── menu.rbf
├── MiSTer*.ini
├── <family>_<date>.rbf
├── config/
├── games/
├── linux/
├── saves/
├── savestates/
└── scripts/
```

Supported core families: `GBA`, `Gameboy`, `MegaCD`, `MegaDrive`, `N64`, `NES`, `NeoGeo`, `PSX`, `Saturn`, `SMS`, `SNES`, `TurboGrafx16`. Each has a `games/` folder of the same name, except `NeoGeo` also uses `NeoGeo-CD/` and `TurboGrafx16` uses `TGFX16/` and `TGFX16-CD/`. `NES/` also holds FDS games; `SMS/` holds SMS games only.

`update.sh` syncs `MiSTer`, `menu.rbf`, Linux files, the newest core of each family (removing older versions), game data and BIOS files, then rebuilds the game cache. Before syncing, it removes everything outside these allowlists and the content listed in `GAME_BLACKLIST`. Saves and save states are never touched.

The scripts keep their state in `scripts/`: `.log`, `.cache`, `.shuffle`, `.mgl` and `.manifest`.
