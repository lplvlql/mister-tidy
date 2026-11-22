#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1:-${ROOT:-/media/fat}}"
GAMES_ROOT="${GAMES_ROOT:-${ROOT%/}/games}"
CACHE_FILE="${CACHE_FILE:-${SCRIPT_DIR}/.cache}"
LOG_FILE="${MISTER_TIDY_LOG_FILE:-${SCRIPT_DIR}/.log}"

mkdir -p "${LOG_FILE%/*}"
exec 2>>"$LOG_FILE"

stage() {
	printf '\n==> %s\n' "$1"
	printf 'stage: %s\n' "$1" >>"$LOG_FILE"
}

stage 'cache'

# Sets CORE for a games-relative path; no subprocesses, extensions match any case.
shopt -s nocasematch
core_for_file() {
	local rel="$1"
	case "${rel%%/*}:${rel##*.}" in
		Gameboy:gb|Gameboy:gbc) CORE=Gameboy ;;
		GBA:gba) CORE=GBA ;;
		NES:nes|NES:fds) CORE=NES ;;
		SNES:sfc|SNES:smc|SNES:bin|SNES:bs) CORE=SNES ;;
		N64:n64|N64:z64) CORE=N64 ;;
		SMS:sms) CORE=SMS ;;
		MegaDrive:bin|MegaDrive:gen|MegaDrive:md) CORE=MegaDrive ;;
		MegaCD:cue|MegaCD:chd) CORE=MegaCD ;;
		NeoGeo:neo|NeoGeo-CD:cue|NeoGeo-CD:chd) CORE=NeoGeo ;;
		TGFX16:bin|TGFX16:pce|TGFX16-CD:cue|TGFX16-CD:chd) CORE=TurboGrafx16 ;;
		PSX:cue|PSX:chd|PSX:exe) CORE=PSX ;;
		Saturn:cue|Saturn:chd) CORE=Saturn ;;
		*) return 1 ;;
	esac
}

build_cache() {
	local tmp
	local folder file rel base scan count
	[[ -d "$GAMES_ROOT" ]] || { echo "Missing games root: $GAMES_ROOT" >&2; return 1; }
	GAMES_ROOT="$(cd -- "$GAMES_ROOT" && pwd -P)"
	[[ ! -d "$CACHE_FILE" ]] || { echo "Cache destination is a directory: $CACHE_FILE" >&2; return 1; }
	tmp="$(mktemp "${CACHE_FILE}.tmp.XXXXXX")"
	cache_tmp="$tmp"
	cache_scan=""
	trap 'rm -f -- "$cache_tmp" "$cache_scan"' EXIT
	scan="$(mktemp "${CACHE_FILE}.scan.XXXXXX")"
	cache_scan="$scan"
	for folder in \
		Gameboy \
		GBA \
		MegaCD \
		MegaDrive \
		N64 \
		NeoGeo \
		NeoGeo-CD \
		NES \
		PSX \
		Saturn \
		SMS \
		SNES \
		TGFX16 \
		TGFX16-CD
	do
		stage "$folder"
		# Unsupported/absent families are optional, but scan errors are fatal.
		[[ -e "$GAMES_ROOT/$folder" || -L "$GAMES_ROOT/$folder" ]] || continue
		if [[ -L "$GAMES_ROOT/$folder" || ! -d "$GAMES_ROOT/$folder" ]] || ! find "$GAMES_ROOT/$folder" -type f -print0 > "$scan"; then
			echo "Failed to scan: $GAMES_ROOT/$folder" >&2
			return 1
		fi
		count=0
		while IFS= read -r -d '' file; do
			rel="${file#$GAMES_ROOT/}"
			base="${rel##*/}"
			case "$base" in
				.*|*"Disc 2"*|*"Disc 3"*|*"Disc 4"*|*"Disc 5"*) continue ;;
			esac
			core_for_file "$rel" || continue
			printf '%s\t%s\n' "$rel" "$CORE"
			count=$((count + 1))
		done < "$scan" >> "$tmp"
		printf '%s: %d games\n' "$folder" "$count" >>"$LOG_FILE"
	done
	[[ ! -d "$CACHE_FILE" ]] || { echo "Cache destination is a directory: $CACHE_FILE" >&2; return 1; }
	mv -f "$tmp" "$CACHE_FILE"
	rm -f "$scan"
	trap - EXIT
}

build_cache
printf 'done\n'
