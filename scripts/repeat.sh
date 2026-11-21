#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1:-${ROOT:-/media/fat}}"
GAMES_ROOT="${GAMES_ROOT:-${ROOT%/}/games}"
MGL_FILE="${MGL_FILE:-${SCRIPT_DIR}/.mgl}"
LOG_FILE="${MISTER_TIDY_LOG_FILE:-${SCRIPT_DIR}/.log}"
MISTER_CMD="${MISTER_CMD:-/dev/MiSTer_cmd}"

mkdir -p "${LOG_FILE%/*}"
exec 2>>"$LOG_FILE"

stage() {
	printf '\n==> %s\n' "$1"
	printf 'stage: %s\n' "$1" >>"$LOG_FILE"
}

stage 'repeat'

if [[ ! -f "$MGL_FILE" ]]; then
	echo "No saved MGL found at ${MGL_FILE}" >&2
	exit 1
fi

rel="$(sed -n 's/.*path="\([^"]*\)".*/\1/p' "$MGL_FILE" | head -n 1)"
if [[ -z "$rel" ]]; then
	echo "Saved MGL does not contain a target path" >&2
	exit 1
fi

# Decode ampersand last to preserve literal entity-looking filename text.
rel="$(printf '%s' "$rel" | sed -e 's/&quot;/"/g' -e 's/&lt;/</g' -e 's/&gt;/>/g' -e 's/&amp;/\&/g')"

# Resolve directory components before checking containment. A text prefix alone
# accepts ../ traversal and symlinked directories leading outside games.
if [[ "$rel" != /* ]] ||
   ! games_path="$(cd -- "$GAMES_ROOT" && pwd -P)" ||
   ! parent_path="$(cd -- "$(dirname -- "$rel")" && pwd -P)"; then
	echo "Cannot resolve saved game path: $rel" >&2
	exit 1
fi
if [[ "$games_path" == / ||
      ( "$parent_path" != "$games_path" && "$parent_path" != "$games_path/"* ) ||
      -L "$rel" ]]; then
	echo "Saved MGL points outside games or targets a symlink: $rel" >&2
	exit 1
fi
rel="${parent_path}/${rel##*/}"

if [[ ! -f "$rel" ]]; then
	echo "Saved game is missing: ${rel}" >&2
	exit 1
fi

printf 'load_core %s\n' "$MGL_FILE" > "$MISTER_CMD"
printf 'done\n'
