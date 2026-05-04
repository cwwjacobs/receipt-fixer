#!/usr/bin/env bash
# Click-to-launch shim — defers to scripts/run_macos.command
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/run_macos.command" "$@"
