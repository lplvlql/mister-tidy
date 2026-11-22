#!/bin/bash

set -euo pipefail

cd -- "$(dirname -- "$0")"

[[ -f .mgl ]] || { echo 'no last game' >&2; exit 1; }

# Decode ampersand last to preserve literal entity-looking filename text.
file="$(sed -n 's/.*path="\([^"]*\)".*/\1/p' .mgl |
  sed -e 's/&quot;/"/g' -e 's/&lt;/</g' -e 's/&gt;/>/g' -e 's/&amp;/\&/g')"

# Resolve folders first: a text prefix alone accepts ../ and symlinked folders.
games="$(cd ../games && pwd -P)"
folder="$(cd -- "$(dirname -- "$file")" && pwd -P)"
if [[ "$folder/" != "$games/"* || -L "$file" || ! -f "$file" ]]; then
  echo "not a game on this card: $file" >&2
  exit 1
fi

# Remove every disc of the game and the tracks its cue sheets name. The chosen
# file goes last, so an interrupted run can be repeated.
name="${file##*/}"
for n in 5 4 3 2 1; do
  disc="$folder/${name/Disc 1/Disc $n}"
  [[ -f "$disc" ]] || continue
  if [[ "$disc" == *.[cC][uU][eE] ]]; then
    while IFS= read -r track; do
      rm -f -- "$folder/${track##*/}"
    done < <(sed -n 's/^[[:space:]]*FILE "\([^"]*[^"/]\)".*/\1/p' "$disc")
  fi
  rm -f -- "$disc"
done
rm -f .mgl
echo "deleted: $name"
