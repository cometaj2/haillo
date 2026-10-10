#!/usr/bin/env bash
# Pulse/PipeWire monitor -> ttyspec.py
# Usage: ./ttyspec.sh [-t fire] [-g] [-b 96] [--mode chunk]
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
py=${SNGLRTTY_PY:-"$here/ttyspec.py"}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    exec python3 "$py" --help
fi

if ! command -v pactl >/dev/null || ! command -v parec >/dev/null; then
    echo "ttyspec: pactl and parec required (pipewire-pulse or pulseaudio)" >&2
    exit 1
fi

sink=$(pactl get-default-sink)
latency=${SNGLRTTY_LATENCY_MS:-20}
export PULSE_LATENCY_MSEC="$latency"
# stdbuf stops glibc from holding a full block before the pipe sees samples.
exec stdbuf -o0 parec \
    --device="${sink}.monitor" \
    --format=float32le \
    --rate=44100 \
    --channels=1 \
    --latency-msec="$latency" \
    | python3 -u "$py" --stdin "$@"
