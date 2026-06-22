#!/bin/zsh
set -u

AGENTS="$HOME/Library/LaunchAgents"
UID_VALUE="$(id -u)"

launchctl bootout "gui/$UID_VALUE" "$AGENTS/com.claracore.innerlife.daemon.plist" 2>/dev/null || true
launchctl bootout "gui/$UID_VALUE" "$AGENTS/com.claracore.innerlife.web.plist" 2>/dev/null || true
rm -f "$AGENTS/com.claracore.innerlife.daemon.plist"
rm -f "$AGENTS/com.claracore.innerlife.web.plist"
echo "InnerLife launchd services removed. Data under ~/.claracore/innerlife was kept."
