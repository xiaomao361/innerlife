#!/bin/zsh
set -eu

SCRIPT_DIR="${0:A:h}"
PROJECT="${SCRIPT_DIR:h}"
if [[ -n "${INNERLIFE_ROOT:-}" ]]; then
  ROOT="$INNERLIFE_ROOT"
elif [[ -d "$HOME/.claracore/innerlife" ]]; then
  ROOT="$HOME/.claracore/innerlife"
else
  ROOT="$HOME/.innerlife"
fi
AGENTS="$HOME/Library/LaunchAgents"
PYTHON="${INNERLIFE_PYTHON:-}"

if [[ -z "$PYTHON" && -x "$PROJECT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT/.venv/bin/python"
fi
if [[ -z "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
  echo "Python 3 was not found. Set INNERLIFE_PYTHON to the project interpreter." >&2
  exit 1
fi
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "InnerLife requires Python 3.10 or newer. Set INNERLIFE_PYTHON to a compatible interpreter." >&2
  exit 1
fi

mkdir -p "$ROOT/logs" "$AGENTS"
chmod +x "$PROJECT/scripts/run_daemon.sh" "$PROJECT/scripts/run_web.sh" "$PROJECT/scripts/run_mcp.sh"

if [[ ! -f "$ROOT/innerlife.env" ]]; then
  sed "s|^INNERLIFE_ROOT=.*|INNERLIFE_ROOT=$ROOT|" \
    "$PROJECT/config/innerlife.env.example" > "$ROOT/innerlife.env"
  chmod 600 "$ROOT/innerlife.env"
  echo "Created $ROOT/innerlife.env — configure models before loading services."
fi
if ! grep -q '^INNERLIFE_PYTHON=' "$ROOT/innerlife.env"; then
  echo "INNERLIFE_PYTHON=$PYTHON" >> "$ROOT/innerlife.env"
fi

sed "s|__HOME__|$HOME|g; s|__PROJECT__|$PROJECT|g; s|__ROOT__|$ROOT|g; s|__PYTHON__|$PYTHON|g" \
  "$PROJECT/config/io.innerlife.daemon.plist.template" \
  > "$AGENTS/io.innerlife.daemon.plist"

sed "s|__HOME__|$HOME|g; s|__PROJECT__|$PROJECT|g; s|__ROOT__|$ROOT|g; s|__PYTHON__|$PYTHON|g" \
  "$PROJECT/config/io.innerlife.web.plist.template" \
  > "$AGENTS/io.innerlife.web.plist"

echo "Installed launchd files."
echo "Python: $PYTHON"
echo "After configuring $ROOT/innerlife.env and creating an agent, run:"
echo "  launchctl bootstrap gui/$(id -u) $AGENTS/io.innerlife.daemon.plist"
echo "  launchctl bootstrap gui/$(id -u) $AGENTS/io.innerlife.web.plist"
