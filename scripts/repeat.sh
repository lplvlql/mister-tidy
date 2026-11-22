#!/bin/bash

set -euo pipefail

cd -- "$(dirname -- "$0")"

[[ -f .mgl ]] || { echo 'no last game' >&2; exit 1; }
printf 'load_core %s\n' "$PWD/.mgl" > /dev/MiSTer_cmd
