#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1:-${ROOT:-/media/fat}}"
GAMES_ROOT="${GAMES_ROOT:-${ROOT%/}/games}"
CACHE_FILE="${CACHE_FILE:-${SCRIPT_DIR}/.cache}"
MGL_FILE="${MGL_FILE:-${SCRIPT_DIR}/.mgl}"
LOG_FILE="${MISTER_TIDY_LOG_FILE:-${SCRIPT_DIR}/.log}"
MISTER_CMD="${MISTER_CMD:-/dev/MiSTer_cmd}"

mkdir -p "${LOG_FILE%/*}"
exec 2>>"$LOG_FILE"

stage() {
	printf '\n==> %s\n' "$1"
	printf 'stage: %s\n' "$1" >>"$LOG_FILE"
}

stage 'random'

params_for_file() {
	local rel="$1"
	local folder="${rel%%/*}"
	local ext="${rel##*.}"
	ext="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"

	case "${folder}:${ext}" in
		Gameboy:gb|Gameboy:gbc|GBA:gba|NES:nes|NES:fds)
			printf 'f 1 2\n'
			;;
		SNES:sfc|SNES:smc|SNES:bin|SNES:bs)
			printf 'f 0 2\n'
			;;
		TGFX16:bin|TGFX16:pce)
			printf 'f 0 1\n'
			;;
		MegaDrive:bin|MegaDrive:gen|MegaDrive:md|SMS:sms|N64:n64|N64:z64|NeoGeo:neo)
			printf 'f 1 1\n'
			;;
		MegaCD:cue|MegaCD:chd|Saturn:cue|Saturn:chd|PSX:cue|PSX:chd|PSX:exe)
			printf 's 0 1\n'
			;;
		TGFX16-CD:cue|TGFX16-CD:chd|NeoGeo-CD:cue|NeoGeo-CD:chd)
			printf 's 1 1\n'
			;;
		*)
			return 1
			;;
	esac
}

xml_escape() {
	# Escape ampersand first; sed replacement literals work across Bash versions.
	printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g'
}

build_mgl() {
	local core="$1"
	local rel="$2"
	local file="${GAMES_ROOT%/}/${rel}"
	local type
	local index
	local delay
	local params tmp escaped_core escaped_file

	if ! params="$(params_for_file "$rel")"; then
		echo "Unsupported game type: $rel" >&2
		return 1
	fi
	read -r type index delay <<<"$params"

	if ! escaped_core="$(xml_escape "$core")" || ! escaped_file="$(xml_escape "$file")"; then
		echo "Failed to escape MGL values" >&2
		return 1
	fi
	if [[ -d "$MGL_FILE" ]]; then
		echo "Failed to write MGL: destination is a directory: $MGL_FILE" >&2
		return 1
	fi
	tmp="$(mktemp "${MGL_FILE}.XXXXXX")" || { echo "Failed to write MGL: $MGL_FILE" >&2; return 1; }
	if ! cat >"$tmp" <<EOF
<mistergamedescription>
  <rbf>${escaped_core}</rbf>
  <file delay="${delay}" type="${type}" index="${index}" path="${escaped_file}"/>
</mistergamedescription>
EOF
	then
		rm -f "$tmp"
		echo "Failed to write MGL: $MGL_FILE" >&2
		return 1
	fi
	if ! mv -f "$tmp" "$MGL_FILE"; then
		rm -f "$tmp"
		echo "Failed to replace MGL: $MGL_FILE" >&2
		return 1
	fi
	printf '%s\n' "$MGL_FILE"
}

random_index() {
	local count="$1" value limit
	# Two 15-bit draws cover large libraries. Reject the uneven tail so every
	# index has the same probability when count does not divide the range.
	(( count > 0 && count <= 1073741824 )) || return 1
	limit=$((1073741824 - 1073741824 % count))
	while :; do
		value=$(((RANDOM << 15) | RANDOM))
		if (( value < limit )); then
			printf '%s\n' "$((value % count))"
			return 0
		fi
	done
}

if [[ ! -s "$CACHE_FILE" ]]; then
	echo "No cache found at ${CACHE_FILE}" >&2
	exit 1
fi

declare -a games=()
while IFS= read -r line; do
	rel="${line%%$'\t'*}"
	[[ -f "${GAMES_ROOT%/}/$rel" ]] || continue
	games+=("$line")
done < "$CACHE_FILE"

if (( ${#games[@]} == 0 )); then
	echo "No launchable games found under $GAMES_ROOT" >&2
	exit 1
fi

index="$(random_index "${#games[@]}")" || exit 1
choice="${games[$index]}"
rel="${choice%%$'\t'*}"
core="${choice#*$'\t'}"

printf 'picked: %s\n' "$rel" >>"$LOG_FILE"

mgl="$(build_mgl "$core" "$rel")" || exit 1
printf 'load_core %s\n' "$mgl" > "$MISTER_CMD"
printf 'done\n'
