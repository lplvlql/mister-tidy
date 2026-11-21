# Mister Tidy Layout

## Goal

Convert a standard MiSTer SD card into the simplified layout used by this repo.

## Entry Point

- `mister-tidy.sh` is the only file the user needs to download at first
- It runs from `scripts/` on MiSTer
- With no argument, it targets `/media/fat`
- With a target argument, it can run against a local path
- After a successful migration it removes itself

## Layout

Keep:

- `MiSTer`
- `menu.rbf`
- the whitelisted `MiSTer*.ini` files
- root `<family>_*.rbf` files for the supported core families
- `config/`
- `games/`
- `linux/`
- `saves/`
- `savestates/`
- `scripts/`

Remove everything else outside the allowlists.

## Canonical Names

Use these canonical labels for folder names and launch families:

- `Gameboy`
- `GBA`
- `MegaCD`
- `MegaDrive`
- `N64`
- `NeoGeo`
- `NES`
- `PSX`
- `Saturn`
- `SMS`
- `SNES`
- `TurboGrafx16`

## Games

Keep only these top-level `games/` folders:

- `GBA`
- `Gameboy`
- `MegaCD`
- `MegaDrive`
- `N64`
- `NeoGeo`
- `NeoGeo-CD`
- `NES`
- `PSX`
- `SMS`
- `SNES`
- `Saturn`
- `TGFX16`
- `TGFX16-CD`

Mapping rules:

- `NES` includes FDS content
- `SMS` contains SMS content only
- `NeoGeo-CD` launches with `NeoGeo`
- `TGFX16-CD` launches with `TurboGrafx16`

## Update

`update.sh` is the on-device sync step.

It should:

- ensure the root folders exist
- sync `MiSTer`, `menu.rbf`, and `linux/` from `Distribution_MiSTer`
- sync the root core `.rbf` files from `Distribution_MiSTer`
- ensure the supported `games/` folders exist
- sync supported `games/` content from `Distribution_MiSTer`
- sync BIOS files into the supported `games/` tree
- sync the helper scripts from this repo

The distribution manifest uses `base_files_url` as the download base.

## Helper Scripts

- `clean.sh` normalizes and prunes
- `update.sh` syncs the layout
- `cache.sh` builds `scripts/.cache`
- `random.sh` builds `scripts/.mgl` and launches it
- `last.sh` reloads `scripts/.mgl`
- `delete.sh` deletes the selected game, removes its cache entries, and clears `scripts/.mgl`

## Runtime Files

- `scripts/.log`
- `scripts/.cache`
- `scripts/.mgl`
- `scripts/.manifest`

## Non-Goals

- Do not format storage
- Do not modify saves or savestates
