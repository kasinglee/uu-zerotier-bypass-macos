#!/bin/sh
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'macOS is required.' >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo 'Run: sudo ./scripts/install.sh' >&2; exit 1; }
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
config_path=${1:-"$repo_dir/config.json"}
[ -f "$config_path" ] || { echo 'Edit the config.json supplied with this repository first.' >&2; exit 1; }
/usr/bin/python3 "$repo_dir/filter.py" --config "$config_path" --check-config
/usr/bin/python3 - "$config_path" <<'PY'
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text())
if c['local_zerotier_ipv4']=='192.0.2.10':
    raise SystemExit('Replace the documentation example IP with this Mac\'s ZeroTier IP.')
if not Path(c['uu_app_path']).is_dir():
    raise SystemExit('UU app directory was not found.')
PY
label=local.uu-zerotier-isolation
app_dir='/Library/Application Support/UUZeroTierIsolation'
plist="/Library/LaunchDaemons/$label.plist"
if /bin/launchctl print "system/$label" >/dev/null 2>&1; then
    /bin/launchctl bootout "system/$label"
fi
/usr/bin/install -d -o root -g wheel -m 755 "$app_dir"
/usr/bin/install -d -o root -g wheel -m 700 '/Library/Logs/UUZeroTierIsolation'
/usr/bin/install -o root -g wheel -m 644 "$repo_dir/filter.py" "$app_dir/filter.py"
/usr/bin/install -o root -g wheel -m 600 "$config_path" "$app_dir/config.json"
/usr/bin/python3 - "$plist" <<'PY'
import plistlib,sys
from pathlib import Path
config={'Label':'local.uu-zerotier-isolation',
'ProgramArguments':['/usr/bin/python3','/Library/Application Support/UUZeroTierIsolation/filter.py'],
'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,'ProcessType':'Background',
'Nice':10,'LowPriorityIO':True,'ExitTimeOut':15,'StandardOutPath':'/dev/null',
'StandardErrorPath':'/Library/Logs/UUZeroTierIsolation/launchd-error.log'}
Path(sys.argv[1]).write_bytes(plistlib.dumps(config))
PY
/usr/sbin/chown root:wheel "$plist"
/bin/chmod 644 "$plist"
/usr/bin/plutil -lint "$plist"
/bin/launchctl enable "system/$label"
/bin/launchctl bootstrap system "$plist"
echo 'Installed and enabled at boot. Check: sudo ./scripts/control.sh status'
