#!/bin/zsh
set -eu

if [[ -n "${INNERLIFE_ROOT:-}" ]]; then
  ROOT="$INNERLIFE_ROOT"
elif [[ -d "$HOME/.claracore/innerlife" ]]; then
  ROOT="$HOME/.claracore/innerlife"
else
  ROOT="$HOME/.innerlife"
fi
ENV_FILE="$ROOT/innerlife.env"
SCRIPT_DIR="${0:A:h}"
PROJECT="${SCRIPT_DIR:h}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

mkdir -p "$ROOT/logs"
PYTHON="${INNERLIFE_PYTHON:-}"
if [[ -z "$PYTHON" && -x "$PROJECT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT/.venv/bin/python"
fi
if [[ -z "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi
cd "$PROJECT"
exec "$PYTHON" "$PROJECT/server/app.py" \
  --host 127.0.0.1 --port 8012
