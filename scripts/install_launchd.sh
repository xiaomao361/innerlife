#!/bin/zsh
set -eu

PROJECT="/Users/zhouwei/Documents/ClaraCore/apps/innerlife"
ROOT="${INNERLIFE_ROOT:-$HOME/.claracore/innerlife}"
AGENTS="$HOME/Library/LaunchAgents"

mkdir -p "$ROOT/logs" "$AGENTS"
chmod +x "$PROJECT/scripts/run_daemon.sh" "$PROJECT/scripts/run_web.sh"

if [[ ! -f "$ROOT/innerlife.env" ]]; then
  cp "$PROJECT/config/innerlife.env.example" "$ROOT/innerlife.env"
  chmod 600 "$ROOT/innerlife.env"
  echo "Created $ROOT/innerlife.env — configure models before loading services."
fi

sed "s|__HOME__|$HOME|g; s|__PROJECT__|$PROJECT|g" \
  "$PROJECT/config/com.claracore.innerlife.daemon.plist.template" \
  > "$AGENTS/com.claracore.innerlife.daemon.plist"

sed "s|__HOME__|$HOME|g; s|__PROJECT__|$PROJECT|g" \
  "$PROJECT/config/com.claracore.innerlife.web.plist.template" \
  > "$AGENTS/com.claracore.innerlife.web.plist"

echo "Installed launchd files."
echo "After configuring $ROOT/innerlife.env, run:"
echo "  launchctl bootstrap gui/$(id -u) $AGENTS/com.claracore.innerlife.daemon.plist"
echo "  launchctl bootstrap gui/$(id -u) $AGENTS/com.claracore.innerlife.web.plist"
