#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run this script with sudo.' >&2; exit 1; }
label=local.uu-zerotier-isolation
plist="/Library/LaunchDaemons/$label.plist"
case "${1:-status}" in
    status)
        /bin/launchctl print "system/$label"
        /sbin/pfctl -a "$label" -vvs rules
        ;;
    stop)
        /bin/launchctl disable "system/$label"
        if /bin/launchctl print "system/$label" >/dev/null 2>&1; then
            /bin/launchctl bootout "system/$label"
        fi
        echo 'Stopped. Automatic startup is disabled.'
        ;;
    start)
        /bin/launchctl enable "system/$label"
        if ! /bin/launchctl print "system/$label" >/dev/null 2>&1; then
            /bin/launchctl bootstrap system "$plist"
        fi
        echo 'Started. Automatic startup is enabled.'
        ;;
    restart)
        /bin/launchctl kickstart -k "system/$label"
        ;;
    *) echo 'Usage: sudo ./scripts/control.sh {status|start|stop|restart}' >&2; exit 1 ;;
esac
