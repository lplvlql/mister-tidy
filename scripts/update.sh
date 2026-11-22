#!/bin/bash

set -euo pipefail
# exFAT ignores case, so names match in any case throughout.
shopt -s nullglob dotglob nocasematch nocaseglob

DIST_URL="${DIST_URL:-https://raw.githubusercontent.com/MiSTer-devel/Distribution_MiSTer/main/db.json.zip}"
BIOS_URL="${BIOS_URL:-https://raw.githubusercontent.com/ajgowans/BiosDB_MiSTer/db/bios_db.json}"
SCRIPTS_URL="${SCRIPTS_URL:-https://raw.githubusercontent.com/lplvlql/mister-tidy/refs/heads/main/scripts}"

GAME_DIRS=(
  GBA
  Gameboy
  MegaCD
  MegaDrive
  N64
  NeoGeo-CD
  NES
  NeoGeo
  PSX
  Saturn
  SMS
  SNES
  TGFX16
  TGFX16-CD
)

GAME_BLACKLIST=(
  "NeoGeo/gog-romsets.xml"
  "NeoGeo/gog-broken-romsets.xml"
)

CORE_NAMES=(
  GBA
  Gameboy
  MegaCD
  MegaDrive
  N64
  NeoGeo
  NES
  PSX
  Saturn
  SMS
  SNES
  TurboGrafx16
)

ROOT_DIRS=(config games linux saves savestates scripts)
SCRIPTS_FILES=(delete.sh repeat.sh shuffle.sh update.sh)
SCRIPTS_STATE=(.cache .shuffle .mgl)

refuse() {
  echo "refusing update: $1" >&2
  exit 1
}

# Validate the card before changing anything.
ROOT="${1-$(dirname -- "${BASH_SOURCE[0]}")/..}"
[[ -n "$ROOT" && -d "$ROOT" ]] || refuse "invalid card directory: $ROOT"
ROOT="$(cd -- "$ROOT" && pwd -P)"
[[ "$ROOT" != / && "$ROOT" != "$(cd -- "$HOME" && pwd -P)" &&
   -f "$ROOT/MiSTer" && -f "$ROOT/menu.rbf" ]] || refuse "not a MiSTer card: $ROOT"
for dir in "${ROOT_DIRS[@]}" "${GAME_DIRS[@]/#/games/}"; do
  path="$ROOT/$dir"
  [[ ! -L "$path" && ( ! -e "$path" || -d "$path" ) ]] || refuse "not a plain folder: $path"
done
# Deleting a mount point would empty whatever is mounted there.
! grep -qsF " $ROOT/" /proc/mounts || refuse "something is mounted under $ROOT"

CACHE_FILE="$ROOT/scripts/.cache"
FAILURES=0

stage() {
  echo "==> $1"
}

remove() {
  rm -rf -- "$1"
  echo "removed: ${1#"$ROOT"/}"
}

# Delete everything in folder $1 that matches none of the other patterns.
prune() {
  local dir="$1" entry pattern
  shift
  for entry in "$dir"/*; do
    for pattern; do
      # shellcheck disable=SC2053  # Patterns must stay unquoted to match.
      [[ "${entry##*/}" != $pattern ]] || continue 2
    done
    remove "$entry"
  done
}

clean_card() {
  local dir banned
  for dir in "${ROOT_DIRS[@]}" "${GAME_DIRS[@]/#/games/}"; do
    mkdir -p "$ROOT/$dir"
  done
  prune "$ROOT" MiSTer menu.rbf 'MiSTer*.ini' "${CORE_NAMES[@]/%/_*.rbf}" "${ROOT_DIRS[@]}"
  prune "$ROOT/games" "${GAME_DIRS[@]}"
  prune "$ROOT/scripts" "${SCRIPTS_FILES[@]}" "${SCRIPTS_STATE[@]}"
  find "$ROOT/games/SMS" -type f -iname '*.gg' -print -exec rm -f {} +
  for banned in "${GAME_BLACKLIST[@]}"; do
    [[ ! -e "$ROOT/games/$banned" ]] || remove "$ROOT/games/$banned"
  done
}

# Reject paths that leave the card, pass through a symlink or name a folder.
safe_destination() {
  local path="$ROOT" part
  local -a parts
  [[ "/$1/" != *//* && "/$1/" != */../* ]] || return 1
  IFS=/ read -r -a parts <<<"$1"
  for part in "${parts[@]}"; do
    path="$path/$part"
    [[ ! -L "$path" ]] || return 1
  done
  [[ ! -d "$path" ]]
}

md5_matches() {
  local got
  got="$(md5sum "$1")" && [[ "${got%% *}" == "$2" ]]
}

# Move a finished download into place unless the card already has it.
install_file() {
  local dest="$ROOT/$2"
  cmp -s "$1" "$dest" && return
  chmod 755 "$1" && mkdir -p "${dest%/*}" && mv -f "$1" "$dest" && echo "updated: $2"
}

# sync_file path url [md5]: manifest files must match their MD5, scripts must parse.
sync_file() {
  local rel="$1" dest="$ROOT/$1" tmp=""
  if ! safe_destination "$rel"; then
    echo "unsafe destination: $rel"
  elif (( $# == 3 )) && [[ -f "$dest" ]] && md5_matches "$dest" "$3"; then
    return 0
  # MiSTer Linux ships no CA bundle, so downloads are not authenticated.
  elif tmp="$(mktemp "$ROOT/.tmp.XXXXXX")" && curl -kfsSL "$2" -o "$tmp" &&
       if (( $# == 3 )); then md5_matches "$tmp" "$3"; else bash -n "$tmp"; fi &&
       install_file "$tmp" "$rel"; then
    rm -f -- "$tmp"
    return 0
  fi
  [[ -z "$tmp" ]] || rm -f -- "$tmp"
  echo "failed: $rel"
  FAILURES=$((FAILURES + 1))
  return 1
}

# Turn a manifest on stdin into lines of path, MD5 and URL; fail if there are none.
read_manifest() {
  jq -er '(.base_files_url // "") as $base | .files | to_entries[] |
    [.key, (.value.hash // ""), (.value.url // ($base + (.key | split("/") | map(@uri) | join("/"))))]
    | join("\u001f")'
}

sync_scripts() {
  local name
  for name in "${SCRIPTS_FILES[@]}"; do
    sync_file "scripts/$name" "$SCRIPTS_URL/$name" || :
  done
}

sync_system() {
  local rel hash url
  while IFS=$'\x1f' read -r rel hash url; do
    case "$rel" in
      MiSTer|menu.rbf|linux/*) sync_file "$rel" "$url" "$hash" || : ;;
    esac
  done <<<"$1"
}

# Install the newest core of each family, then remove every other one.
sync_cores() {
  local family name hash url old
  for family in "${CORE_NAMES[@]}"; do
    # Names differ only by date, so the newest sorts last.
    IFS=$'\x1f' read -r name hash url < <(
      grep -E "^_Console/${family}_[0-9]{8}\.rbf" <<<"$1" | sort | tail -n 1) || continue
    name="${name##*/}"
    sync_file "$name" "$url" "$hash" || continue
    for old in "$ROOT/${family}"_*.rbf; do
      [[ -f "$old" && "${old##*/}" != "$name" ]] || continue
      remove "$old"
    done
  done
}

sync_games() {
  local rel hash url folder banned
  while IFS=$'\x1f' read -r rel hash url; do
    for folder in "${GAME_DIRS[@]}"; do
      [[ "$rel" == "games/$folder/"* ]] || continue
      rel="games/$folder/${rel#*/*/}"
      for banned in "${GAME_BLACKLIST[@]}"; do
        [[ "$rel/" != "games/$banned/"* ]] || continue 3
      done
      sync_file "$rel" "$url" "$hash" || :
      break
    done
  done <<<"$1"
}

# Write one line per game: path, tab, then "core type index delay" for its MGL.
build_cache() {
  (cd -- "$ROOT/games" && find "${GAME_DIRS[@]}" -type f ! -name '.*' ! -name '*Disc [2-5]*') |
  while IFS= read -r rel; do
    case "${rel%%/*}:${rel##*.}" in
      Gameboy:gb|Gameboy:gbc) launch='Gameboy f 1 2' ;;
      GBA:gba) launch='GBA f 1 2' ;;
      NES:nes|NES:fds) launch='NES f 1 2' ;;
      SNES:sfc|SNES:smc|SNES:bin|SNES:bs) launch='SNES f 0 2' ;;
      N64:n64|N64:z64) launch='N64 f 1 1' ;;
      SMS:sms) launch='SMS f 1 1' ;;
      MegaDrive:bin|MegaDrive:gen|MegaDrive:md) launch='MegaDrive f 1 1' ;;
      MegaCD:cue|MegaCD:chd) launch='MegaCD s 0 1' ;;
      NeoGeo:neo) launch='NeoGeo f 1 1' ;;
      NeoGeo-CD:cue|NeoGeo-CD:chd) launch='NeoGeo s 1 1' ;;
      TGFX16:bin|TGFX16:pce) launch='TurboGrafx16 f 0 1' ;;
      TGFX16-CD:cue|TGFX16-CD:chd) launch='TurboGrafx16 s 1 1' ;;
      PSX:cue|PSX:chd|PSX:exe) launch='PSX s 0 1' ;;
      Saturn:cue|Saturn:chd) launch='Saturn s 0 1' ;;
      *) continue ;;
    esac
    printf '%s\t%s\n' "$rel" "$launch"
  done > "$CACHE_FILE.tmp"
  mv -f "$CACHE_FILE.tmp" "$CACHE_FILE"
}

main() {
  local dist bios
  stage tidy
  clean_card
  # Neither of these depends on the manifests, so a bad one cannot block them.
  stage scripts
  sync_scripts
  stage cache
  build_cache
  stage manifests
  zip="$(mktemp)"
  trap 'rm -f -- "$zip"' EXIT
  if ! curl -kfsSL "$DIST_URL" -o "$zip" ||
     ! dist="$(unzip -p "$zip" | read_manifest)" ||
     ! bios="$(curl -kfsSL "$BIOS_URL" | read_manifest)"; then
    echo 'failed: manifests'
    return 1
  fi
  stage system
  sync_system "$dist"
  stage cores
  sync_cores "$dist"
  stage games
  sync_games "$dist"
  sync_games "$bios"
  (( FAILURES == 0 )) || { echo "$FAILURES failed"; return 1; }
  echo 'done'
}

# One line, so nothing is read from this file after main replaces it.
main; exit
