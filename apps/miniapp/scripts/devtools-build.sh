#!/bin/sh
set -eu
PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
export PATH
if ! command -v node >/dev/null 2>&1 || ! command -v pnpm >/dev/null 2>&1; then
  if command -v fnm >/dev/null 2>&1; then
    eval "$(fnm env --shell bash)"
  fi
fi
exec pnpm run build
