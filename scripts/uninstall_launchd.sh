#!/bin/zsh
set -u

AGENTS="$HOME/Library/LaunchAgents"
UID_VALUE="$(id -u)"

launchctl bootout "gui/$UID_VALUE" "$AGENTS/io.innerlife.daemon.plist" 2>/dev/null || true
launchctl bootout "gui/$UID_VALUE" "$AGENTS/io.innerlife.web.plist" 2>/dev/null || true
rm -f "$AGENTS/io.innerlife.daemon.plist"
rm -f "$AGENTS/io.innerlife.web.plist"
echo "InnerLife launchd services removed. Stored data was kept."
