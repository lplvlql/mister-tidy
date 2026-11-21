#!/bin/bash

set -euo pipefail

# Reject an explicitly empty target.
ROOT="${1-${ROOT-/media/fat}}"
[[ -n "$ROOT" && -d "$ROOT" ]] || { echo "invalid card directory: $ROOT" >&2; exit 1; }
ROOT_PATH="$(cd -- "$ROOT" && pwd -P)"
HOME_PATH="$(cd -- "$HOME" && pwd -P)"
if [[ "$ROOT_PATH" == / || "$ROOT_PATH" == "$HOME_PATH" ||
      ! -f "$ROOT_PATH/MiSTer" || ! -f "$ROOT_PATH/menu.rbf" ]]; then
  echo "refusing cleanup: target must be a MiSTer card, not / or home" >&2
  exit 1
fi
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${MISTER_TIDY_LOG_FILE:-${SCRIPT_DIR}/.log}"

mkdir -p "${LOG_FILE%/*}"
exec 2>>"$LOG_FILE"

stage() {
  printf '\n==> %s\n' "$1"
  printf 'stage: %s\n' "$1" >>"$LOG_FILE"
}

ROOT_FILES=(
  "MiSTer"
  "menu.rbf"
)

ROOT_INI_PREFIXES=(
  "MiSTer"
)

CORE_NAMES=(
  "GBA"
  "Gameboy"
  "MegaCD"
  "MegaDrive"
  "N64"
  "NES"
  "NeoGeo"
  "PSX"
  "Saturn"
  "SMS"
  "SNES"
  "TurboGrafx16"
)

ROOT_DIRS=(
  "config"
  "games"
  "linux"
  "saves"
  "savestates"
  "scripts"
)

SCRIPTS_FILES=(
  "mister-tidy.sh"
  ".cache.sh"
  ".clean.sh"
  "delete.sh"
  "repeat.sh"
  "shuffle.sh"
  "update.sh"
  ".cache"
  ".shuffle"
  "clean.sh"
  "cache.sh"
  "random.sh"
  "last.sh"
  ".mgl"
  ".manifest"
  ".log"
)

GAME_DIRS=(
  "GBA"
  "Gameboy"
  "MegaCD"
  "MegaDrive"
  "N64"
  "NES"
  "NeoGeo-CD"
  "NeoGeo"
  "PSX"
  "SMS"
  "SNES"
  "Saturn"
  "TGFX16"
  "TGFX16-CD"
)

GAME_BLACKLIST=(
  "Gameboy/Palettes"
  "NES/Palettes"
  "PSX/240p Test Suite"
  "PSX/PadTest 1.1"
  "SNES/240p Test Suite"
  "MegaDrive/240p Test Suite.bin"
  "N64/N64 Controller Tester.z64"
  "NeoGeo/gog-romsets.xml"
  "NeoGeo/gog-broken-romsets.xml"
)

lowercase() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

check_destination() {
  local entry="$1" dst="$2"
  if [[ ( -e "$dst" || -L "$dst" ) && ! "$entry" -ef "$dst" ]]; then
    echo "refusing normalization collision: $entry -> $dst" >&2
    exit 1
  fi
}

move_or_rename() {
  local entry="$1" dst="$2" tmp
  check_destination "$entry" "$dst"
  if [[ "$entry" -ef "$dst" ]]; then
    # On a case-insensitive card both spellings identify the same directory.
    # Use a unique temporary directory without deleting either spelling.
    tmp="$(mktemp -d "${entry%/*}/.mister-rename.XXXXXX")"
    mv "$entry" "$tmp/entry"
    mv "$tmp/entry" "$dst"
    rmdir "$tmp"
  else
    mv "$entry" "$dst"
  fi
}

# Check for name collisions and directory symlinks before pruning.
preflight() {
  local entry base canonical child child_name
  for entry in "$ROOT_PATH"/* "$ROOT_PATH"/.*; do
    [[ -e "$entry" || -L "$entry" ]] || continue
    base="${entry##*/}"
    case "$base" in .|..) continue ;; esac
    if canonical="$(canonical_from_whitelist "$base" "${ROOT_DIRS[@]}")"; then
      [[ ! -L "$entry" && -d "$entry" ]] || { echo "invalid card folder: $entry" >&2; exit 1; }
      check_destination "$entry" "$ROOT_PATH/$canonical"
      if [[ "$canonical" == games ]]; then
        for child in "$entry"/* "$entry"/.*; do
          [[ -e "$child" || -L "$child" ]] || continue
          child_name="${child##*/}"
          case "$child_name" in .|..) continue ;; esac
          if canonical="$(canonical_from_whitelist "$child_name" "${GAME_DIRS[@]}")"; then
            [[ ! -L "$child" && -d "$child" ]] || { echo "invalid game folder: $child" >&2; exit 1; }
            check_destination "$child" "$entry/$canonical"
          fi
        done
      fi
    fi
  done
}

canonical_from_whitelist() {
  local name="$1"
  shift
  local allowed
  for allowed in "$@"; do
    if [[ "$(lowercase "$name")" == "$(lowercase "$allowed")" ]]; then
      printf '%s\n' "$allowed"
      return 0
    fi
  done
  return 1
}

normalize_root() {
  local entry base dst
  for entry in "${ROOT_PATH}"/* "${ROOT_PATH}"/.*; do
    [[ -e "$entry" || -L "$entry" ]] || continue
    case "${entry##*/}" in
      .|..) continue ;;
    esac
    base="${entry##*/}"
    if ! dst="$(canonical_from_whitelist "$base" "${ROOT_DIRS[@]}")"; then
      continue
    fi
    dst="${ROOT_PATH}/${dst}"
    if [[ "$entry" != "$dst" ]]; then
      move_or_rename "$entry" "$dst"
    fi
  done
}

prune_root() {
  local entry base keep prefix
  for entry in "${ROOT_PATH}"/* "${ROOT_PATH}"/.*; do
    [[ -e "$entry" || -L "$entry" ]] || continue
    case "${entry##*/}" in
      .|..) continue ;;
    esac
    base="${entry##*/}"
    keep=0
    for allowed in "${ROOT_FILES[@]}" "${ROOT_DIRS[@]}"; do
      if [[ "$base" == "$allowed" ]]; then
        keep=1
        break
      fi
    done
    case "$base" in
      *.ini)
        if [[ "$keep" -eq 1 ]]; then
          continue
        fi
        for prefix in "${ROOT_INI_PREFIXES[@]}"; do
          if [[ "$base" == "${prefix}"* ]]; then
            keep=1
            break
          fi
        done
        ;;
      *.rbf)
        if [[ "$keep" -eq 1 ]]; then
          continue
        fi
        keep=0
        for prefix in "${CORE_NAMES[@]}"; do
          if [[ "$base" == "${prefix}"_*".rbf" ]]; then
            keep=1
            break
          fi
        done
        ;;
    esac
    if [[ "$keep" -eq 0 ]]; then
      rm -rf "$entry"
    fi
  done
}

normalize_games() {
  local entry base dst
  for entry in "${ROOT_PATH}/games"/* "${ROOT_PATH}/games"/.*; do
    [[ -e "$entry" || -L "$entry" ]] || continue
    case "${entry##*/}" in
      .|..) continue ;;
    esac
    base="${entry##*/}"
    if ! dst="$(canonical_from_whitelist "$base" "${GAME_DIRS[@]}")"; then
      continue
    fi
    dst="${ROOT_PATH}/games/${dst}"
    if [[ "$entry" != "$dst" ]]; then
      move_or_rename "$entry" "$dst"
    fi
  done
}

prune_games() {
  local entry name keep banned
  if [[ -d "${ROOT_PATH}/games" ]]; then
    if [[ -d "${ROOT_PATH}/games/SMS" ]]; then
      find "${ROOT_PATH}/games/SMS" -type f -iname '*.gg' -exec rm -f {} +
    fi
    for banned in "${GAME_BLACKLIST[@]}"; do
      rm -rf "${ROOT_PATH}/games/${banned}"
    done

    for entry in "${ROOT_PATH}/games"/* "${ROOT_PATH}/games"/.*; do
      [[ -e "$entry" || -L "$entry" ]] || continue
      name="${entry##*/}"
      case "$name" in .|..) continue ;; esac
      keep=0
      for allowed in "${GAME_DIRS[@]}"; do
        if [[ "$name" == "$allowed" ]]; then
          keep=1
          break
        fi
      done
      [[ "$keep" -eq 1 ]] || rm -rf "$entry"
    done
  fi
}

prune_scripts() {
  local entry name keep
  if [[ -d "${ROOT_PATH}/scripts" ]]; then
    for entry in "${ROOT_PATH}/scripts"/* "${ROOT_PATH}/scripts"/.*; do
      [[ -e "$entry" || -L "$entry" ]] || continue
      name="${entry##*/}"
      case "$name" in .|..) continue ;; esac
      keep=0
      for allowed in "${SCRIPTS_FILES[@]}"; do
        if [[ "$(lowercase "$name")" == "$(lowercase "$allowed")" ]]; then
          keep=1
          break
        fi
      done
      if [[ "$keep" -eq 0 ]]; then
        rm -rf "$entry"
      fi
    done
  fi
}

preflight

stage 'normalize root'
normalize_root
stage 'prune root'
prune_root
stage 'normalize games'
normalize_games
stage 'prune games'
prune_games
stage 'prune scripts'
prune_scripts

printf 'clean done\n'
