#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run: sudo ./scripts/uninstall.sh' >&2; exit 1; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
/bin/sh "$script_dir/control.sh" stop
# The daemon removes its own PF anchor when stopped. Keep unrelated PF rules.
if /sbin/pfctl -sr 2>/dev/null | /usr/bin/grep -F 'anchor "local.uu-zerotier-isolation"' >/dev/null; then
    echo 'The PF anchor is still attached. Inspect the service log before removing files.' >&2
    exit 1
fi
/bin/rm -f /Library/LaunchDaemons/local.uu-zerotier-isolation.plist
/bin/rm -f '/Library/Application Support/UUZeroTierIsolation/filter.py' '/Library/Application Support/UUZeroTierIsolation/config.json'
/bin/rmdir '/Library/Application Support/UUZeroTierIsolation' 2>/dev/null || true
echo 'Uninstalled. Diagnostic logs are retained in /Library/Logs/UUZeroTierIsolation.'
