#!/usr/bin/python3
"""Keep UU sockets off the configured ZeroTier interface using native PF."""
import argparse
import ctypes
import ipaddress
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import subprocess
import time

ANCHOR = 'local.uu-zerotier-isolation'
ROOT_LINE = f'anchor "{ANCHOR}" quick all'
ADDRESS = None
APP_CONTENTS = None
PROCESS_PREFIX = None
POLL_INTERVAL = None
STATE = Path('/var/run/uu-zerotier-isolation')
LOGDIR = Path('/Library/Logs/UUZeroTierIsolation')
PROC = ctypes.CDLL('/usr/lib/libproc.dylib')
PROC.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
PROC.proc_pidpath.restype = ctypes.c_int

def run(args, text=None, check=True):
    result = subprocess.run(args, input=text, text=True, capture_output=True, timeout=10)
    if check and result.returncode:
        raise RuntimeError(f'{args}: {result.stderr.strip()}')
    return result

def root_rules():
    return run(['/sbin/pfctl', '-sr']).stdout

def load_root(rules):
    run(['/sbin/pfctl', '-n', '-R', '-f', '-'], rules)
    run(['/sbin/pfctl', '-R', '-f', '-'], rules)

def interface():
    data = run(['/sbin/ifconfig']).stdout
    for block in re.split(r'(?=^\S[^\n]*: flags=)', data, flags=re.M):
        if re.search(r'\binet ' + re.escape(ADDRESS) + r'\s', block):
            name = block.split(':', 1)[0]
            if re.fullmatch(r'feth\d+', name):
                return name
    return None

def is_uu(pid):
    buffer = ctypes.create_string_buffer(4096)
    count = PROC.proc_pidpath(pid, buffer, len(buffer))
    return count > 0 and buffer.value.decode(errors='replace').startswith(APP_CONTENTS)

def ports():
    result = run(['/usr/sbin/lsof', '-nP', '-a', '-c', PROCESS_PREFIX, '-i', '-FpcPnt'], check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError('Cannot inspect UU sockets')
    found = {'TCP': set(), 'UDP': set()}
    proto = None
    accepted = False
    for line in result.stdout.splitlines():
        if line.startswith('p'):
            accepted = is_uu(int(line[1:]))
            proto = None
        elif line.startswith('f'):
            proto = None
        elif line.startswith('P'):
            proto = line[1:]
        elif accepted and line.startswith('n') and proto in found:
            local = line[1:].split('->', 1)[0]
            match = re.fullmatch(r'(' + re.escape(ADDRESS) + r'|\*|\[::\]):(\d+)', local)
            if match:
                found[proto].add(int(match.group(2)))
    return found

def build_rules(iface, found):
    lines = []
    if iface:
        for proto, values in found.items():
            if values:
                port_set = '{ ' + ', '.join(map(str, sorted(values))) + ' }'
                lines.extend([
                    f'block return in quick on {iface} proto {proto.lower()} from any to any port {port_set}',
                    f'block return out quick on {iface} proto {proto.lower()} from any port {port_set} to any',
                ])
    return '\n'.join(lines) + '\n'

def remove_own_anchor():
    live = root_rules()
    lines = [line for line in live.splitlines() if f'"{ANCHOR}"' not in line]
    clean = '\n'.join(lines) + ('\n' if lines else '')
    if clean != live:
        load_root(clean)
    run(['/sbin/pfctl', '-a', ANCHOR, '-F', 'rules'], check=False)

def load_config(path):
    data = json.loads(Path(path).read_text())
    required = {'local_zerotier_ipv4', 'uu_app_path', 'poll_interval_seconds', 'process_name_prefix'}
    if set(data) != required:
        raise ValueError('Config must contain exactly: ' + ', '.join(sorted(required)))
    if not isinstance(data['local_zerotier_ipv4'], str):
        raise ValueError('local_zerotier_ipv4 must be an IPv4 string')
    address = str(ipaddress.IPv4Address(data['local_zerotier_ipv4']))
    app = data['uu_app_path']
    if not isinstance(app, str) or not app.startswith('/') or not app.endswith('.app'):
        raise ValueError('uu_app_path must be an absolute .app path')
    interval = data['poll_interval_seconds']
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not .2 <= interval <= 10:
        raise ValueError('poll_interval_seconds must be between 0.2 and 10')
    prefix = data['process_name_prefix']
    if not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', prefix):
        raise ValueError('Invalid process_name_prefix')
    return address, app.rstrip('/') + '/Contents/', prefix, float(interval)

def main():
    global ADDRESS, APP_CONTENTS, PROCESS_PREFIX, POLL_INTERVAL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/Library/Application Support/UUZeroTierIsolation/config.json')
    parser.add_argument('--check-config', action='store_true', help='Validate configuration without touching PF')
    args = parser.parse_args()
    ADDRESS, APP_CONTENTS, PROCESS_PREFIX, POLL_INTERVAL = load_config(args.config)
    if args.check_config:
        print('Configuration is valid')
        return
    if os.geteuid() != 0:
        raise SystemExit('Administrator privileges required')
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    LOGDIR.mkdir(mode=0o700, exist_ok=True)
    lock = (STATE / 'lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    handler = RotatingFileHandler(LOGDIR / 'events.log', maxBytes=1_000_000, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    token = None
    stop = False
    def stop_signal(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    try:
        # A previous unclean exit may have left our own rules/reference behind.
        remove_own_anchor()
        token_file = STATE / 'token'
        if token_file.exists():
            old = token_file.read_text().strip()
            if old.isdigit():
                run(['/sbin/pfctl', '-X', old], check=False)
            token_file.unlink()
        original = root_rules()
        (STATE / 'filter-before-start.rules').write_text(original)
        initial = build_rules(interface(), ports())
        run(['/sbin/pfctl', '-n', '-a', ANCHOR, '-f', '-'], initial)
        run(['/sbin/pfctl', '-a', ANCHOR, '-f', '-'], initial)
        load_root(ROOT_LINE + '\n' + original)
        result = run(['/sbin/pfctl', '-E'])
        match = re.search(r'Token\s*:\s*(\d+)', result.stdout + result.stderr)
        if not match:
            raise RuntimeError('PF did not return its enable-reference token')
        token = match.group(1)
        token_file.write_text(token)
        (STATE / 'pid').write_text(str(os.getpid()))
        previous = None
        last_check = time.monotonic()
        logging.info('Started')
        while not stop:
            iface = interface()
            found = ports() if iface else {'TCP': set(), 'UDP': set()}
            rules = build_rules(iface, found)
            if rules != previous:
                run(['/sbin/pfctl', '-a', ANCHOR, '-f', '-'], rules)
                status = {'pid': os.getpid(), 'interface': iface, 'address': ADDRESS,
                          'ports': {key: sorted(value) for key, value in found.items()}, 'updated': time.time()}
                (STATE / 'current.rules').write_text(rules)
                (STATE / 'status.json').write_text(json.dumps(status))
                logging.info('Rules updated: %s', status)
                previous = rules
            if time.monotonic() - last_check >= 5:
                if ANCHOR not in root_rules():
                    raise RuntimeError('Another service replaced the filter rules; restarting safely')
                last_check = time.monotonic()
            time.sleep(POLL_INTERVAL)
    except Exception:
        logging.exception('Filter stopped after an error')
        raise
    finally:
        try:
            remove_own_anchor()
        finally:
            if token:
                released = run(['/sbin/pfctl', '-X', token], check=False)
                if released.returncode == 0:
                    (STATE / 'token').unlink(missing_ok=True)
            (STATE / 'pid').unlink(missing_ok=True)
            logging.info('Stopped; own filter rules removed')

if __name__ == '__main__':
    main()
