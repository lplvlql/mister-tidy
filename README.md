# Mister Tidy

Mister Tidy puts console launchers directly in the MiSTer boot menu.

## Install

**Back up your SD card first.** Every update deletes files outside the layout below, including anything you add later.

Copy `scripts/update.sh` to the SD card’s `scripts/` folder and run it from the MiSTer Scripts menu. It installs the other scripts and keeps itself up to date. It works on the card it sits on; pass a path to use another. It refuses to run while anything is mounted inside the card.

Downloads are not authenticated, because MiSTer Linux has no CA bundle. Cores, system files and BIOS are checked against an MD5 list, but that list and the scripts are trusted as received. Use a network you trust.

## Scripts menu

| Script | Action |
| --- | --- |
| `update.sh` | Tidy the card, rebuild the game cache and update everything |
| `shuffle.sh` | Launch a random game, never repeating one until every game has played |
| `repeat.sh` | Relaunch the last game |
| `delete.sh` | Delete the last game, including its tracks and other discs in the same folder |

`update.sh` shows what it updates and ends with `done` only if nothing failed.

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

`update.sh` first updates the scripts, switching to its own new version if there is one. It removes everything outside this layout, then Game Gear ROMs in `SMS/` and the unused `gog-*` lists in `NeoGeo/`. Names match in any case. It then rebuilds the game cache and syncs `MiSTer`, `menu.rbf`, Linux support files, the newest core of each family (removing every other version), game data and BIOS files. Game data and BIOS files that differ from the manifests are replaced. `saves/` and `savestates/` are never touched.

The scripts keep their state in `scripts/`: `.cache`, `.shuffle` and `.mgl`.
