#!/bin/zsh
set -eu

ROOT="${INNERLIFE_ROOT:-$HOME/.claracore/innerlife}"
ENV_FILE="$ROOT/innerlife.env"
HERMES_ENV="$HOME/.hermes/.env"

if [[ -f "$HERMES_ENV" ]]; then
  set -a
  source "$HERMES_ENV"
  set +a
fi
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

mkdir -p "$ROOT/logs"
exec /Users/zhouwei/miniconda3/envs/zhouwei/bin/python \
  -m innerlife.daemon
