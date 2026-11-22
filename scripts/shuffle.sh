#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1:-${ROOT:-/media/fat}}"
GAMES_ROOT="${GAMES_ROOT:-${ROOT%/}/games}"
CACHE_FILE="${CACHE_FILE:-${SCRIPT_DIR}/.cache}"
SHUFFLE_FILE="${SHUFFLE_FILE:-${SCRIPT_DIR}/.shuffle}"
MGL_FILE="${MGL_FILE:-${SCRIPT_DIR}/.mgl}"
LOG_FILE="${MISTER_TIDY_LOG_FILE:-${SCRIPT_DIR}/.log}"
MISTER_CMD="${MISTER_CMD:-/dev/MiSTer_cmd}"

mkdir -p "${LOG_FILE%/*}"
exec 2>>"$LOG_FILE"

stage() {
	printf '\n==> %s\n' "$1"
	printf 'stage: %s\n' "$1" >>"$LOG_FILE"
}

stage 'shuffle'

xml_escape() {
	# Escape ampersand first; sed replacement literals work across Bash versions.
	printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g'
}

# The cache's second column is "core type index delay" (see build_cache in update.sh).
build_mgl() {
	local launch="$1"
	local rel="$2"
	local file="${GAMES_ROOT%/}/${rel}"
	local core type index delay tmp escaped_core escaped_file

	read -r core type index delay <<<"$launch"
	if [[ -z "$delay" ]]; then
		echo "Unsupported game type: $rel" >&2
		return 1
	fi

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

if [[ -e "$SHUFFLE_FILE" || -L "$SHUFFLE_FILE" ]]; then
	[[ -f "$SHUFFLE_FILE" && ! -L "$SHUFFLE_FILE" ]] || {
		echo "Invalid shuffle history: $SHUFFLE_FILE" >&2
		exit 1
	}
	history="$SHUFFLE_FILE"
else
	history=/dev/null
fi

# Mark played paths before checking which cached games still exist.
entries="$(awk -F '\t' '
	FILENAME == ARGV[1] { played[$0] = 1; next }
	{ print (($1 in played) ? "1" : "0") $0 }
' "$history" "$CACHE_FILE")" || exit 1

declare -a games=() remaining=()
while IFS= read -r entry; do
	line="${entry:1}"
	rel="${line%%$'\t'*}"
	[[ -f "${GAMES_ROOT%/}/$rel" ]] || continue
	games+=("$line")
	if [[ "${entry:0:1}" == 0 ]]; then
		remaining+=("$line")
	fi
done <<< "$entries"

if (( ${#games[@]} == 0 )); then
	echo "No launchable games found under $GAMES_ROOT" >&2
	exit 1
fi

if (( ${#remaining[@]} > 0 )); then
	games=("${remaining[@]}")
else
	history=/dev/null
fi

index="$(random_index "${#games[@]}")" || exit 1
choice="${games[$index]}"
rel="${choice%%$'\t'*}"
launch="${choice#*$'\t'}"

printf 'picked: %s\n' "$rel" >>"$LOG_FILE"

history_tmp="$(mktemp "${SHUFFLE_FILE}.tmp.XXXXXX")"
trap 'rm -f -- "$history_tmp"' EXIT
if [[ "$history" != /dev/null ]]; then
	cat -- "$history" > "$history_tmp"
fi
printf '%s\n' "$rel" >> "$history_tmp"

mgl="$(build_mgl "$launch" "$rel")" || exit 1
printf 'load_core %s\n' "$mgl" > "$MISTER_CMD"
mv -f -- "$history_tmp" "$SHUFFLE_FILE"
printf 'done\n'
