#!/usr/bin/env bash
# Click-to-launch shim — defers to scripts/run_linux.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/run_linux.sh" "$@"
