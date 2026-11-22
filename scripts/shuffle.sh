#!/bin/bash

set -euo pipefail

cd -- "$(dirname -- "$0")"

GAMES="$(cd .. && pwd)/games"
[[ -s .cache ]] || { echo 'no game cache; run update.sh' >&2; exit 1; }

# Set rel and launch to a random game that exists and is not listed in file $1.
pick() {
  while IFS=$'\t' read -r _ rel launch; do
    [[ ! -f "$GAMES/$rel" ]] || return 0
  done < <(awk -F '\t' -v seed="$((RANDOM << 15 | RANDOM))" '
    BEGIN { srand(seed) }
    FILENAME == ARGV[1] { played[$0]; next }
    !($1 in played) { printf "%.9f\t%s\n", rand(), $0 }
  ' "$1" .cache | sort -n 2>/dev/null)
  return 1
}

touch .shuffle
if ! pick .shuffle; then
  pick /dev/null || { echo 'no games found' >&2; exit 1; }
  : > .shuffle
fi

# Escape ampersand first.
path="$(printf '%s' "$GAMES/$rel" |
  sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g')"
read -r core type index delay <<<"$launch"
cat > .mgl <<EOF
<mistergamedescription>
  <rbf>${core}</rbf>
  <file delay="${delay}" type="${type}" index="${index}" path="${path}"/>
</mistergamedescription>
EOF
printf 'load_core %s\n' "$PWD/.mgl" > /dev/MiSTer_cmd
printf '%s\n' "$rel" >> .shuffle
echo "playing: $rel"
