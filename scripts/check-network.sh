#!/bin/zsh
# macOS 开发的兼容入口。
set -euo pipefail
exec /bin/zsh "${0:A:h}/dev/check-network.sh" "$@"
