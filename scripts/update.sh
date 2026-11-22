#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${1-$(cd -- "${SCRIPT_DIR}/.." && pwd)}"
# Validate the card before making changes.
[[ -n "$ROOT" && -d "$ROOT" ]] || { echo "invalid card directory: $ROOT" >&2; exit 1; }
ROOT="$(cd -- "$ROOT" && pwd -P)"
HOME_PATH="$(cd -- "$HOME" && pwd -P)"
if [[ "$ROOT" == / || "$ROOT" == "$HOME_PATH" ||
      ! -f "$ROOT/MiSTer" || ! -f "$ROOT/menu.rbf" ]]; then
  echo "refusing update: target must be a MiSTer card, not / or home" >&2
  exit 1
fi
SCRIPTS_ROOT="${ROOT%/}/scripts"
LOG_FILE="${MISTER_TIDY_LOG_FILE:-${SCRIPT_DIR}/.log}"
MANIFEST_FILE="${MANIFEST_FILE:-${SCRIPTS_ROOT}/.manifest}"

mkdir -p "${LOG_FILE%/*}"
exec 2>>"$LOG_FILE"

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

ROOT_DIRS=(
  config
  games
  linux
  saves
  savestates
  scripts
)

ROOT_FILES=(
  MiSTer
  menu.rbf
)

SCRIPTS_FILES=(
  .clean.sh
  .cache.sh
  delete.sh
  repeat.sh
  shuffle.sh
  update.sh
)

done_line() {
  printf '%s\n' "$1" >>"$LOG_FILE"
}

stage() {
  printf '\n==> %s\n' "$1"
  printf 'stage: %s\n' "$1" >>"$LOG_FILE"
}

# Parse a manifest once into lines of key, hash and download url, joined by the
# unit separator so empty fields never collapse. A file's own url wins;
# otherwise the url is the base plus the encoded path.
read_manifest() {
  jq -r '(.base_files_url // "") as $base | .files | to_entries[] |
    [.key, (.value.hash // ""),
     (.value.url // ($base + (.key | ltrimstr("|") | split("/") | map(@uri) | join("/"))))]
    | join("\u001f")' <<<"$1"
}

validate_manifest() {
  # Require exactly one valid manifest before syncing files.
  jq -e -s '
    length == 1 and (.[0] |
      type == "object" and
      (.base_files_url == null or (.base_files_url | type == "string" and length > 0)) and
      (.files | type == "object") and
      all(.files[];
        type == "object" and
        (.hash == null or (.hash | type == "string"))))
  ' <<<"$1" >/dev/null
}

# Download results: 0 copied, 1 hash matched, 2 checksum mismatch,
# 3 transfer failed, 4 local file operation failed, 5 hash check failed.
FAILURES=0

download() {
  download_with_md5 "$1" "$2" ""
}

download_with_md5() {
  local url="$1" dest="$2" hash="$3" tmp got mode=644
  [[ ! -d "$dest" ]] || return 4
  mkdir -p "$(dirname -- "$dest")" || return 4
  if [[ -n "$hash" && -f "$dest" ]]; then
    got="$(md5sum "$dest")" || return 5
    got="${got%% *}"
    [[ "$got" != "$hash" ]] || return 1
  fi
  if [[ -f "$dest" ]]; then
    # GNU stat on MiSTer/Linux; BSD stat on macOS.
    mode="$(stat -c '%a' "$dest" 2>/dev/null || stat -f '%Lp' "$dest")" || return 4
  fi
  tmp="$(mktemp "${dest}.tmp.XXXXXX")" || return 4
  # MiSTer Linux ships no CA bundle; files are verified by manifest MD5 instead.
  if ! curl -kfsSL "$url" -o "$tmp"; then
    rm -f -- "$tmp"
    return 3
  fi
  if [[ -n "$hash" ]]; then
    if ! got="$(md5sum "$tmp")"; then
      rm -f -- "$tmp"
      return 5
    fi
    got="${got%% *}"
    if [[ "$got" != "$hash" ]]; then
      rm -f -- "$tmp"
      return 2
    fi
  fi
  if ! chmod "$mode" "$tmp"; then
    rm -f -- "$tmp"
    return 4
  fi
  if [[ -d "$dest" ]] || ! mv -f "$tmp" "$dest"; then
    rm -f -- "$tmp"
    return 4
  fi
  return 0
}

record_failure() {
  done_line "failed: $1 ($2)"
  FAILURES=$((FAILURES + 1))
}

safe_destination() {
  local rel="$1" part path="$ROOT"
  local -a parts
  case "$rel" in
    ''|/*|*/|*//*|*$'\n'*|*$'\r'*|*$'\t'*) return 1 ;;
  esac
  IFS=/ read -r -a parts <<<"$rel"
  for part in "${parts[@]}"; do
    case "$part" in ''|.|..) return 1 ;; esac
    path="$path/$part"
    # Reject symlink components, including a final file symlink.
    [[ ! -L "$path" ]] || return 1
  done
  [[ ! -d "$path" ]]
}

sync_download() {
  local name="$1" url="$2" dest="$3" hash="${4:-}" result reason
  if ! safe_destination "$name"; then
    record_failure "$name" "unsafe destination"
    return 2
  fi
  if download_with_md5 "$url" "$dest" "$hash"; then
    done_line "copied: $name"
    return 0
  else
    result=$?
  fi
  case "$result" in
    1) done_line "unchanged: $name"; return 1 ;;
    2) reason="checksum mismatch" ;;
    3) reason="download failed" ;;
    4) reason="local file operation failed" ;;
    5) reason="hash check failed" ;;
    *) reason="unexpected download error: $result" ;;
  esac
  record_failure "$name" "$reason"
  return 2
}

fetch_distribution_manifest() {
  mkdir -p "$(dirname -- "$MANIFEST_FILE")"
  download "$DIST_URL" "$MANIFEST_FILE" || return $?
  if [[ "$(file -b --mime-type "$MANIFEST_FILE")" == "application/zip" ]]; then
    unzip -p "$MANIFEST_FILE" '*.json'
  else
    cat "$MANIFEST_FILE"
  fi
}

ensure_layout() {
  local d
  for d in "${ROOT_DIRS[@]}"; do
    if [[ -L "$ROOT/$d" ]]; then
      record_failure "$d" "unsafe destination"
      return 1
    fi
  done
  for d in "${ROOT_DIRS[@]}"; do
    mkdir -p "$ROOT/$d"
  done
  mkdir -p "$SCRIPTS_ROOT"
}

sync_root() {
  local key name hash file_url rel result
  while IFS=$'\x1f' read -r key hash file_url; do
    [[ -n "$key" ]] || continue
    rel="${key#|}"
    [[ "$rel" == */* ]] && continue
    name="${rel##*/}"
    local allowed keep=0
    for allowed in "${ROOT_FILES[@]}"; do
      if [[ "$name" == "$allowed" ]]; then
        keep=1
        break
      fi
    done
    [[ "$keep" -eq 1 ]] || continue
    if sync_download "$name" "$file_url" "$ROOT/$name" "$hash"; then
      result=0
    else
      result=$?
    fi
    if [[ "$result" -le 1 && "$name" == MiSTer ]]; then
      if ! chmod a+x "$ROOT/$name"; then
        record_failure "$name" "chmod failed"
      fi
    fi
  done < <(sed -n '/^[^|]/p' <<<"$1")
}

sync_linux() {
  local key rel hash file_url
  while IFS=$'\x1f' read -r key hash file_url; do
    rel="${key#|}"
    [[ "$rel" == linux/* ]] || continue
    sync_download "$rel" "$file_url" "$ROOT/$rel" "$hash" || :
  done <<<"$1"
}

sync_cores() {
  local consoles family key rel name hash best_date best_key best_hash best_url old file_url
  consoles="$(grep -F '_Console/' <<<"$1" || :)"
  for family in "${CORE_NAMES[@]}"; do
    best_date=""
    best_key=""
    best_hash=""
    best_url=""
    printf 'core family: %s\n' "$family" >>"$LOG_FILE"
    while IFS=$'\x1f' read -r key hash file_url; do
      rel="${key#|}"
      [[ "$rel" == _Console/* ]] || continue
      name="${rel##*/}"
      [[ "$name" == ${family}_*.rbf ]] || continue
      printf 'core candidate: %s\n' "$name" >>"$LOG_FILE"
      if [[ "$name" =~ _([0-9]{8})\.rbf$ ]]; then
        if [[ -z "$best_date" || "${BASH_REMATCH[1]}" > "$best_date" ]]; then
          best_date="${BASH_REMATCH[1]}"
          best_key="$key"
          best_hash="$hash"
          best_url="$file_url"
        fi
      fi
    done <<<"$consoles"
    [[ -n "$best_url" ]] || continue
    name="${best_key#|}"
    name="${name##*/}"
    printf 'core match: %s -> %s\n' "$best_key" "$ROOT/$name" >>"$LOG_FILE"
    # Once the newest core is in place, drop the older dated versions it replaces.
    sync_download "$name" "$best_url" "$ROOT/$name" "$best_hash" || [[ $? -eq 1 ]] || continue
    for old in "$ROOT/${family}"_*.rbf; do
      [[ -f "$old" && "${old##*/}" != "$name" ]] || continue
      rm -f -- "$old" && done_line "removed: ${old##*/}"
    done
  done
}

ensure_game_folders() {
  local folder
  for folder in "${GAME_DIRS[@]}"; do
    mkdir -p "$ROOT/games/$folder"
  done
}

game_excluded() {
  local rel="${1#games/}" banned
  for banned in "${GAME_BLACKLIST[@]}"; do
    case "$rel" in
      "$banned"|"$banned"/*) return 0 ;;
    esac
  done
  return 1
}

sync_games() {
  local preserve_unhashed="${2:-0}" key rel hash file_url family dest allowed keep
  while IFS=$'\x1f' read -r key hash file_url; do
    rel="${key#|}"
    [[ "$rel" == games/* ]] || continue
    game_excluded "$rel" && continue
    [[ "$rel" == *.[gG][gG] ]] && continue
    family="${rel#games/}"
    family="${family%%/*}"
    keep=0
    for allowed in "${GAME_DIRS[@]}"; do
      if [[ "$family" == "$allowed" ]]; then
        keep=1
        break
      fi
    done
    [[ "$keep" -eq 1 ]] || continue
    dest="$ROOT/$rel"
    if ! safe_destination "$rel"; then
      record_failure "$rel" "unsafe destination"
      continue
    fi
    if [[ "$preserve_unhashed" -eq 1 && -z "$hash" && -f "$dest" ]]; then
      done_line "unchanged: $rel"
    else
      sync_download "$rel" "$file_url" "$dest" "$hash" || :
    fi
  done <<<"$1"
}

sync_scripts() {
  local name url result
  for name in "${SCRIPTS_FILES[@]}"; do
    url="$SCRIPTS_URL/$name"
    if sync_download "scripts/$name" "$url" "$SCRIPTS_ROOT/$name"; then
      result=0
    else
      result=$?
    fi
    if [[ "$result" -le 1 ]]; then
      if ! chmod a+x "$SCRIPTS_ROOT/$name"; then
        record_failure "scripts/$name" "chmod failed"
      fi
    fi
  done
}

main() {
  local distribution_manifest bios_manifest distribution_entries bios_entries
  ensure_layout
  stage distribution
  if ! distribution_manifest="$(fetch_distribution_manifest)"; then
    record_failure "distribution manifest" "fetch or extraction failed"
    return 1
  fi
  if ! validate_manifest "$distribution_manifest"; then
    record_failure "distribution manifest" "invalid JSON or structure"
    return 1
  fi
  stage bios
  if ! bios_manifest="$(curl -kfsSL "$BIOS_URL")"; then
    record_failure "BIOS manifest" "download failed"
    return 1
  fi
  if ! validate_manifest "$bios_manifest"; then
    record_failure "BIOS manifest" "invalid JSON or structure"
    return 1
  fi
  # Parse each manifest once; every stage reads the same entries.
  distribution_entries="$(read_manifest "$distribution_manifest")"
  bios_entries="$(read_manifest "$bios_manifest")"
  stage root
  sync_root "$distribution_entries"
  stage linux
  sync_linux "$distribution_entries"
  stage cores
  sync_cores "$distribution_entries"
  stage games
  ensure_game_folders
  sync_games "$distribution_entries"
  sync_games "$bios_entries" 1
  stage scripts
  sync_scripts
  if [[ "$FAILURES" -ne 0 ]]; then
    done_line "update failed: $FAILURES failure(s)"
    return 1
  fi
  stage cache
  MISTER_TIDY_LOG_FILE="$LOG_FILE" "$SCRIPTS_ROOT/.cache.sh" "$ROOT"
  rm -f -- "$SCRIPTS_ROOT/clean.sh" "$SCRIPTS_ROOT/cache.sh" \
    "$SCRIPTS_ROOT/random.sh" "$SCRIPTS_ROOT/last.sh"
}

main
