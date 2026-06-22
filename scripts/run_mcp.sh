#!/bin/zsh
set -eu

ROOT="${INNERLIFE_ROOT:-$HOME/.claracore/innerlife}"
HERMES_ENV="$HOME/.hermes/.env"
INNERLIFE_ENV="$ROOT/innerlife.env"

if [[ -f "$HERMES_ENV" ]]; then
  set -a
  source "$HERMES_ENV"
  set +a
fi

if [[ -f "$INNERLIFE_ENV" ]]; then
  set -a
  source "$INNERLIFE_ENV"
  set +a
fi

exec /Users/zhouwei/miniconda3/envs/zhouwei/bin/python \
  /Users/zhouwei/Documents/ClaraCore/apps/innerlife/server/mcp.py
