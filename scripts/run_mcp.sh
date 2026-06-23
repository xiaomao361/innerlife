#!/bin/zsh
set -eu

if [[ -n "${INNERLIFE_ROOT:-}" ]]; then
  ROOT="$INNERLIFE_ROOT"
elif [[ -d "$HOME/.claracore/innerlife" ]]; then
  ROOT="$HOME/.claracore/innerlife"
else
  ROOT="$HOME/.innerlife"
fi
INNERLIFE_ENV="$ROOT/innerlife.env"
SCRIPT_DIR="${0:A:h}"
PROJECT="${SCRIPT_DIR:h}"

if [[ -f "$INNERLIFE_ENV" ]]; then
  set -a
  source "$INNERLIFE_ENV"
  set +a
fi

PYTHON="${INNERLIFE_PYTHON:-}"
if [[ -z "$PYTHON" && -x "$PROJECT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT/.venv/bin/python"
fi
if [[ -z "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi
cd "$PROJECT"
exec "$PYTHON" "$PROJECT/server/mcp_server.py"
