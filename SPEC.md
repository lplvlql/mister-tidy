# Mister Tidy Layout

`mister-tidy.sh` installs the helpers, then runs `.clean.sh` and `update.sh`. The updater runs `.cache.sh` after a successful sync.

## Card root

Keep `MiSTer`, `menu.rbf`, `MiSTer*.ini`, the supported core files, and these directories:

`config/`, `games/`, `linux/`, `saves/`, `savestates/`, `scripts/`

Core files use `<family>_<date>.rbf`. Supported families:

- `GBA`, `Gameboy`, `MegaCD`, `MegaDrive`
- `N64`, `NES`, `NeoGeo`, `PSX`
- `Saturn`, `SMS`, `SNES`, `TurboGrafx16`

## Games

Keep a `games/` folder for each family above, with these exceptions:

- `NeoGeo` also launches games in `NeoGeo-CD/`.
- `TurboGrafx16` uses `TGFX16/` and `TGFX16-CD/`.
- `NES/` also holds FDS content. `SMS/` holds SMS content only.

`.clean.sh` removes entries outside the allowlists and removes the blocked content listed in `GAME_BLACKLIST`.

## Updates and runtime files

`update.sh` creates the supported folders and uses the distribution manifest’s `base_files_url` to sync `MiSTer`, `menu.rbf`, Linux files, cores, and supported game data. It also syncs BIOS files from BiosDB and helpers from this repo.

The helpers keep their log, game cache, shuffle history, launch file, and manifest in `scripts/` as `.log`, `.cache`, `.shuffle`, `.mgl`, and `.manifest`.

Migration leaves saves and save states intact and performs no formatting.
