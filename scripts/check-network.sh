#!/bin/zsh
# Compatibility entry point for macOS development.
set -euo pipefail
exec /bin/zsh "${0:A:h}/dev/check-network.sh" "$@"
