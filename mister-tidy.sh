#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1-/media/fat}"
# Validate before creating logs, installing payloads, or removing anything.
[[ -n "$ROOT" && -d "$ROOT" ]] || { echo "invalid card directory: $ROOT" >&2; exit 1; }
ROOT_DIR="$(cd -- "$ROOT" && pwd -P)"
HOME_PATH="$(cd -- "$HOME" && pwd -P)"
if [[ "$ROOT_DIR" == / || "$ROOT_DIR" == "$HOME_PATH" ||
      ! -f "$ROOT_DIR/MiSTer" || ! -f "$ROOT_DIR/menu.rbf" ||
      -L "$ROOT_DIR/scripts" ||
      ( -e "$ROOT_DIR/scripts" && ! -d "$ROOT_DIR/scripts" ) ]]; then
  echo "refusing migration: target must be a MiSTer card with a real scripts directory" >&2
  exit 1
fi
SCRIPTS_ROOT="${ROOT_DIR}/scripts"
script_name="${0##*/}"
REPO_BASE_URL="${REPO_BASE_URL:-https://raw.githubusercontent.com/lplvlql/mister-tidy/refs/heads/main}"
LOG_FILE="${SCRIPTS_ROOT}/.log"

ROOT_FILES=(
  "MiSTer"
  "menu.rbf"
)

SCRIPTS_FILES=(
  clean.sh
  cache.sh
  delete.sh
  last.sh
  random.sh
  update.sh
)

require_root_file() {
  local name="$1"
  if [[ ! -e "${ROOT_DIR}/${name}" ]]; then
    echo "missing required file: $name" >&2
    exit 1
  fi
}

install_payload() {
  mkdir -p "$SCRIPTS_ROOT"
  local name
  for name in "${SCRIPTS_FILES[@]}"; do
    fetch_script "scripts/$name" "${SCRIPTS_ROOT}/$name"
  done
}

fetch_script() {
  local remote_path="$1"
  local dest="$2"
  local url="${REPO_BASE_URL}/${remote_path}"
  local tmp
  [[ ! -d "$dest" ]] || { echo "script destination is a directory: $dest" >&2; return 1; }
  tmp="$(mktemp "${dest}.tmp.XXXXXX")" || return 1

  if [[ "$url" == file://* ]]; then
    local source_path="${url#file://}"
    cp "$source_path" "$tmp" || { rm -f -- "$tmp"; return 1; }
  elif command -v curl >/dev/null 2>&1; then
    curl -kfsSL "$url" -o "$tmp" || { rm -f -- "$tmp"; return 1; }
  else
    rm -f -- "$tmp"
    echo "curl is required to fetch scripts: $url" >&2
    exit 1
  fi

  # Publish each helper ready to run, even if a later download fails.
  if ! chmod a+rx "$tmp"; then
    rm -f -- "$tmp"
    return 1
  fi
  if [[ -d "$dest" ]] || ! mv -f "$tmp" "$dest"; then
    rm -f -- "$tmp"
    return 1
  fi
}

ensure_bootstrap_scripts() {
  mkdir -p "$SCRIPTS_ROOT"
  local name
  for name in "${SCRIPTS_FILES[@]}"; do
    [[ -x "${SCRIPTS_ROOT}/${name}" ]] || return 1
  done
}

main() {
  mkdir -p "$SCRIPTS_ROOT"
  export MISTER_TIDY_LOG_FILE="$LOG_FILE"
  mkdir -p "${LOG_FILE%/*}"
  exec 2>>"$LOG_FILE"
  run_stamp="$(date '+%Y-%m-%d %H:%M:%S')"
  printf '==> migrate\n'
  printf 'run: %s\n' "$run_stamp" >>"$LOG_FILE"
  for name in "${ROOT_FILES[@]}"; do
    require_root_file "$name"
  done
  install_payload
  ensure_bootstrap_scripts
  "${SCRIPTS_ROOT}/clean.sh" "$ROOT_DIR"
  "${SCRIPTS_ROOT}/update.sh" "$ROOT_DIR"
  "${SCRIPTS_ROOT}/cache.sh" "$ROOT_DIR"
  rm -f "${SCRIPTS_ROOT}/${script_name}"
  printf 'migration complete\n'
}

main
