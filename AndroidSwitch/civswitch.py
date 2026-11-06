#!/usr/bin/env python3
"""Own the Android USB gadget and HID transport for the entire session."""

import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from functionfs import FunctionFSHID
from macro_player import ASCII_TO_KEY, play_payload

BASE = Path(__file__).resolve().parent
STATE = Path('/data/local/tmp/civswitch-state')
BACKUP = STATE / 'usb.json'
SESSION = STATE / 'session.json'
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
DEVICE = {
    'bcdUSB': '0x0200', 'bcdDevice': '0x0100',
    'bDeviceClass': '0', 'bDeviceSubClass': '0', 'bDeviceProtocol': '0',
    'idVendor': '0x0f0d', 'idProduct': '0x0092',
    'strings/0x409/manufacturer': 'PICO SWITCH PRO.',
    'strings/0x409/product': 'J24 CONTROLLER',
    'strings/0x409/serialnumber': '',
}
FUNCTION = 'ffs.civswitch'
MOUNTPOINT = Path('/dev/usb-ffs/civswitch')


# Main command


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('test', 'run', 'teardown'))
    parser.add_argument('--start-delay', '--delay', type=float, default=2)
    parser.add_argument('--connect-timeout', type=float, default=90)
    parser.add_argument('--usb-trace', action='store_true', help='Log USB control requests.')
    args = parser.parse_args(argv)

    if os.geteuid() != 0:
        parser.error('Root access is required. Use npm run start or npm run test in Termux.')

    if (not math.isfinite(args.start_delay) or not math.isfinite(args.connect_timeout)
            or args.start_delay < 0 or args.connect_timeout <= 0):
        parser.error('Delays must be nonnegative and connection timeout positive and finite.')

    # Read the whole request before changing USB or SELinux.
    lines = read_request(sys.stdin, args.mode)
    ensure_state_directory()

    # Every copy of this project shares the same phone and the same lock.
    with open(STATE / 'session.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another CivSwitch session is running. Stop it first.')

        previous = {name: signal.signal(name, stop_session) for name in SIGNALS}
        try:
            disconnected = watch_launcher(sys.stdin)

            # Finish any interrupted session before starting another one.
            with uninterrupted_cleanup():
                restore_session()

            if disconnected.is_set():
                raise KeyboardInterrupt

            if args.mode == 'teardown':
                print('USB and SELinux recovery complete; no pending session.', flush=True)
                return 0

            check_legacy_backup()
            run_usb_session(args, lines)
            return 0
        except KeyboardInterrupt:
            print('\nSession stopped; USB and SELinux restored.', flush=True)
            return 130
        finally:
            for name, handler in previous.items():
                signal.signal(name, handler)


# Phone and file helpers


def write_once(path, data):
    """Write a ConfigFS setting in one call, as Android's USB driver expects."""
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_TRUNC)
    except OSError as e:
        raise OSError(e.errno, f'{path}: {e.strerror or e}') from e

    try:
        written = os.write(fd, data)
        if written != len(data):
            raise OSError(f'{path}: short write {written}/{len(data)}')
    except OSError as e:
        raise OSError(e.errno, f'{path}: {e.strerror or e}') from e
    finally:
        os.close(fd)


def getprop(name):
    return subprocess.check_output(['getprop', name], text=True).strip()


def setprop(name, value):
    subprocess.run(['setprop', name, value], check=True)


def find_gadget():
    for root in (Path('/config/usb_gadget'), Path('/sys/kernel/config/usb_gadget')):
        if not root.is_dir():
            continue

        candidates = [p for p in sorted(root.iterdir())
                      if (p / 'configs').is_dir() and list((p / 'configs').iterdir())]
        bound = [p for p in candidates if (p / 'UDC').read_text().strip()]

        if len(bound) == 1:
            return bound[0]

        if len(candidates) == 1:
            return candidates[0]

        if candidates:
            raise RuntimeError('Multiple USB gadgets found; cannot choose an owner safely.')

    raise RuntimeError('No Android USB gadget found. Check ConfigFS and root access.')


def find_musb_speed():
    # Older MUSB drivers ignore the generic ConfigFS maximum speed setting.
    for candidate in ('/sys/module/musb_hdrc/parameters/speed',
                      '/sys/module/mt_usb/parameters/speed',
                      '/sys/module/musb/parameters/speed'):
        p = Path(candidate)
        if p.exists():
            return p

    return None


def mounted(path):
    return any(line.split()[1] == str(path)
               for line in Path('/proc/mounts').read_text().splitlines())


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    with open(temp, 'w', encoding='utf-8') as f:
        os.chmod(temp, 0o600)
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, path)


# USB gadget


class Gadget:
    def __init__(self, path=None, backup=BACKUP):
        self.path = Path(path) if path else find_gadget()
        self.backup = Path(backup)
        self.snapshot = None
        self.udc = None
        self.config = self.configuration()
        self.mountpoint = MOUNTPOINT

    def configuration(self):
        configs = sorted((self.path / 'configs').iterdir())
        if len(configs) != 1:
            raise RuntimeError('Expected one Android USB configuration; '
                               'refusing to leave additional configurations active.')

        return configs[0]

    def links(self):
        result = {}
        config_dir = self.config
        for p in config_dir.iterdir():
            if p.is_symlink():
                target = os.readlink(p)
                if not os.path.isabs(target):
                    target = os.path.normpath(os.path.join(str(config_dir), target))

                result[p.name] = target

        return result

    def clear_links(self):
        for name in self.links():
            (self.config / name).unlink()

    def save(self):
        if self.backup.exists():
            raise RuntimeError('A USB backup already exists; recover it with npm run teardown.')

        function = self.path / 'functions' / FUNCTION
        if function.exists() or mounted(self.mountpoint):
            raise RuntimeError('An existing CivSwitch FunctionFS instance has no backup. '
                               'Reboot Android before starting a new session.')

        config = self.config.relative_to(self.path)
        paths = list(DEVICE) + ['UDC', 'max_speed', 'os_desc/use',
                               f'{config}/bmAttributes', f'{config}/MaxPower',
                               f'{config}/strings/0x409/configuration']
        attrs = {name: (self.path / name).read_bytes().hex()
                 for name in paths if (self.path / name).exists()}
        musb_speed_path = find_musb_speed()
        musb_speed_saved = None
        if musb_speed_path:
            musb_speed_saved = {'path': str(musb_speed_path),
                                'value': musb_speed_path.read_text().strip()}

        snapshot = {
            'gadget': str(self.path), 'attrs': attrs, 'links': self.links(),
            'config': str(config), 'function': FUNCTION,
            'mountpoint': str(self.mountpoint),
            'mountpoint_existed': self.mountpoint.exists(),
            'configfs_property': getprop('sys.usb.configfs'),
            'adbd_running': getprop('init.svc.adbd') == 'running',
            'musb_speed': musb_speed_saved,
        }

        # Publish only a complete backup; never overwrite a previous session.
        atomic_json(self.backup, snapshot)
        self.snapshot = snapshot

    def prepare(self):
        if 'functionfs' not in Path('/proc/filesystems').read_text().split():
            raise RuntimeError('FunctionFS is unavailable. Kernel needs CONFIG_USB_F_FS '
                               'and CONFIG_USB_CONFIGFS_F_FS (built in or loaded).')

        self.save()
        self.udc = bytes.fromhex(self.snapshot['attrs']['UDC']).decode().strip()

        if not self.udc:
            controllers = sorted(Path('/sys/class/udc').iterdir())
            if not controllers:
                raise RuntimeError('No USB Device Controller found.')

            self.udc = controllers[0].name

        setprop('sys.usb.configfs', '0')
        self.unbind()

        if self.snapshot['adbd_running']:
            subprocess.run(['stop', 'adbd'], check=True)
            deadline = time.monotonic() + 5

            while getprop('init.svc.adbd') != 'stopped':
                if time.monotonic() >= deadline:
                    raise RuntimeError('ADB did not stop; cannot take ownership of USB.')

                time.sleep(.05)

        self.clear_links()
        (self.path / 'strings/0x409').mkdir(exist_ok=True)

        for name, value in DEVICE.items():
            write_once(self.path / name, (value + '\n').encode())

        write_once(self.config / 'bmAttributes', b'0x80\n')
        write_once(self.config / 'MaxPower', b'500\n')

        config_string = self.config / 'strings/0x409/configuration'
        if config_string.exists():
            write_once(config_string, b'\n')

        if (self.path / 'os_desc/use').exists():
            write_once(self.path / 'os_desc/use', b'0\n')

        max_speed = self.path / 'max_speed'
        musb_speed_path = find_musb_speed()
        if musb_speed_path:
            write_once(musb_speed_path, b'0\n')
            print(f'  Full-speed requested via {musb_speed_path}', flush=True)
        elif max_speed.exists():
            write_once(max_speed, b'full-speed\n')
            print('  Maximum speed: full-speed (ConfigFS)', flush=True)
        elif not max_speed.exists():
            print('  Speed control unavailable; using controller default.', flush=True)

        (self.path / 'functions' / FUNCTION).mkdir()
        self.mountpoint.mkdir(parents=True, exist_ok=True)
        subprocess.run(['mount', '-t', 'functionfs', 'civswitch', str(self.mountpoint)],
                       check=True)

        print('  FunctionFS mounted; HID reports: gamepad=86, keyboard=63 bytes.', flush=True)
        print('  If the connection remains high-speed, unplug and reconnect the USB cable.', flush=True)

    def bind(self):
        (self.config / 'f1').symlink_to(self.path / 'functions' / FUNCTION)
        write_once(self.path / 'UDC', (self.udc + '\n').encode())

    def unbind(self):
        # Linux returns ENODEV for an empty UDC if it is already unbound.
        if (self.path / 'UDC').read_text().strip():
            write_once(self.path / 'UDC', b'\n')

    def state(self):
        return (Path('/sys/class/udc') / self.udc / 'state').read_text().strip()

    def speed(self):
        path = Path('/sys/class/udc') / self.udc / 'current_speed'
        return path.read_text().strip() if path.exists() else '?'

    def restore(self):
        snapshot = self.snapshot
        if snapshot is None:
            if not self.backup.exists():
                return

            snapshot = json.loads(self.backup.read_text())

        self.path = Path(snapshot['gadget'])
        self.config = self.path / snapshot['config']
        self.mountpoint = Path(snapshot['mountpoint'])

        print('Restoring Android USB...', flush=True)
        setprop('sys.usb.configfs', '0')

        try:
            # Remove our USB function before restoring Android's configuration.
            self.unbind()
            self.clear_links()

            if mounted(self.mountpoint):
                subprocess.run(['umount', str(self.mountpoint)], check=True)

            function = self.path / 'functions' / snapshot['function']
            if function.exists():
                function.rmdir()

            if not snapshot['mountpoint_existed'] and self.mountpoint.exists():
                self.mountpoint.rmdir()

            # Put back the saved settings while the gadget is disconnected.
            attrs = snapshot['attrs']
            for name, value in attrs.items():
                if name != 'UDC':
                    write_once(self.path / name, bytes.fromhex(value))

            # Restore speed before binding: controllers latch it at startup.
            musb_speed = snapshot.get('musb_speed')
            if musb_speed:
                write_once(Path(musb_speed['path']),
                           (musb_speed['value'] + '\n').encode())

            for name, target in snapshot['links'].items():
                (self.config / name).symlink_to(target)

            # ADB must finish preparing its USB interface before we reconnect.
            if snapshot['adbd_running']:
                subprocess.run(['start', 'adbd'], check=True)
                deadline = time.monotonic() + 5

                while getprop('sys.usb.ffs.ready') != '1':
                    if time.monotonic() >= deadline:
                        raise RuntimeError('ADB FunctionFS descriptors did not become ready.')

                    time.sleep(.05)

            original_udc = bytes.fromhex(attrs['UDC']).strip()
            if original_udc:
                write_once(self.path / 'UDC', original_udc + b'\n')
        finally:
            setprop('sys.usb.configfs', snapshot['configfs_property'])

            if snapshot['adbd_running'] and getprop('init.svc.adbd') == 'stopped':
                subprocess.run(['start', 'adbd'], check=True)

        self.backup.unlink()
        self.snapshot = None
        print('Android USB restored.', flush=True)


def wait_connected(gadget, hid, timeout):
    deadline = time.monotonic() + timeout
    next_status = time.monotonic() + 5
    while time.monotonic() < deadline:
        hid.check()

        if gadget.state() == 'configured':
            # FunctionFS counts completed IN transfers, not write attempts.
            if all(n >= 2 for n in hid.counts()):
                print(f'USB configured, speed={gadget.speed()}; '
                      'both HID interfaces are completing reports.', flush=True)
                return

        if time.monotonic() >= next_status:
            print(f'Waiting: USB {gadget.state()}, speed={gadget.speed()}, '
                  f'reports={hid.counts()}, errors={hid.write_errors()}', flush=True)
            next_status = time.monotonic() + 5

        time.sleep(.02)

    raise RuntimeError(f'USB connection timed out: state={gadget.state()}, '
                       f'reports completed (gamepad, keyboard)={hid.counts()}')


# Session and recovery


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def selinux_state():
    state = subprocess.check_output(['getenforce'], text=True).strip()
    if state not in ('Enforcing', 'Permissive', 'Disabled'):
        raise RuntimeError(f'Unknown SELinux state: {state!r}')

    return state


def set_selinux(state):
    current = selinux_state()
    if current == state:
        return

    if state == 'Disabled' or current == 'Disabled':
        raise RuntimeError(f'Cannot change SELinux from {current} to {state}.')

    subprocess.run(['setenforce', '1' if state == 'Enforcing' else '0'], check=True)

    if selinux_state() != state:
        raise RuntimeError(f'SELinux did not switch to {state}.')

    print(f'SELinux: {state}', flush=True)


def make_permissive():
    if selinux_state() != 'Disabled':
        set_selinux('Permissive')


def begin_session():
    # Persist the original state before the first privileged change. This file
    # also covers a failure in gadget discovery, before a USB backup exists.
    atomic_json(SESSION, {'selinux': selinux_state(), 'boot_id': boot_id()})

    make_permissive()


@contextmanager
def uninterrupted_cleanup():
    # Repeated Ctrl+C must not interrupt restoration halfway through.
    previous = {name: signal.signal(name, signal.SIG_IGN) for name in SIGNALS}
    try:
        yield
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)


def restore_session():
    if not SESSION.exists():
        if BACKUP.exists():
            raise RuntimeError('USB backup has no SELinux journal; keeping it for recovery.')

        return

    try:
        saved = json.loads(SESSION.read_text())
    except ValueError as exc:
        raise RuntimeError('Invalid session journal; keeping it for recovery.') from exc

    if (not isinstance(saved, dict)
            or saved.get('selinux') not in ('Enforcing', 'Permissive', 'Disabled')
            or not isinstance(saved.get('boot_id'), str)):
        raise RuntimeError('Invalid session journal; keeping it for recovery.')

    if saved['boot_id'] != boot_id():
        # Reboot resets USB and SELinux. Never replay a snapshot from a previous boot.
        BACKUP.unlink(missing_ok=True)
        SESSION.unlink()
        print('Discarded session state from a previous boot.', flush=True)
        return

    errors = []
    try:
        if BACKUP.exists():
            make_permissive()
            snapshot = json.loads(BACKUP.read_text())
            Gadget(path=snapshot['gadget'], backup=BACKUP).restore()
    except Exception as exc:
        errors.append(f'USB: {exc}')
    finally:
        try:
            set_selinux(saved['selinux'])
        except Exception as exc:
            errors.append(f'SELinux: {exc}')

    if errors:
        raise RuntimeError('Restoration failed; run npm run teardown. ' + '; '.join(errors))

    SESSION.unlink()


def finish_session(gadget, hid):
    errors = []

    # Unbinding cancels endpoint requests before AIO buffers are freed. Every
    # cleanup step is attempted even if a previous step failed.
    actions = []
    if hid is not None:
        actions.append(hid.stop)

    if gadget is not None and gadget.snapshot is not None:
        actions.append(gadget.unbind)

    if hid is not None:
        actions.append(hid.close)

    actions.append(restore_session)

    for action in actions:
        try:
            action()
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        raise RuntimeError('Session cleanup failed: ' + '; '.join(errors))


def check_legacy_backup():
    for old in (BASE / '.gadget_backup.json',
                Path('/data/local/tmp/civswitch/.gadget_backup.json')):
        if old.exists():
            raise RuntimeError(f'Old USB backup found at {old}. Restore it with the old '
                               'installation before updating, or reboot and remove the stale backup.')


def run_usb_session(args, lines):
    gadget = None
    hid = None

    try:
        begin_session()

        gadget = Gadget(backup=BACKUP)
        print('Preparing Switch gamepad + keyboard...', flush=True)
        gadget.prepare()

        hid = FunctionFSHID(gadget.mountpoint, trace=args.usb_trace)
        print('Plug the phone into the Switch dock. Starting continuous reports now.', flush=True)
        gadget.bind()
        wait_connected(gadget, hid, args.connect_timeout)

        print(f'Starting {args.mode} in {args.start_delay:g}s; neutral reports remain active.', flush=True)
        hid.sleep(args.start_delay)
        play_payload(hid, lines if lines is not None else [
            'gezine is a goat',
            'Test OK! Run npm run start for the full payload',
        ])
        hid.sleep(.1)
    finally:
        original_error = sys.exc_info()[1]

        # Finish recovery even if the user presses Ctrl+C again.
        with uninterrupted_cleanup():
            try:
                finish_session(gadget, hid)
            except Exception as exc:
                if original_error is not None:
                    raise RuntimeError(f'{original_error}; {exc}') from exc

                raise


def watch_launcher(stream):
    disconnected = threading.Event()

    def watch():
        try:
            # After the initial request, the pipe stays open until cancellation.
            # Raw reads avoid holding stdin's buffered lock during interpreter
            # shutdown while this daemon thread is still waiting for EOF.
            os.read(stream.fileno(), 1)
        finally:
            disconnected.set()
            os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=watch, daemon=True).start()
    return disconnected


def read_request(stream, mode):
    """Reject incomplete or unsupported chat lines before taking over USB."""
    try:
        request = json.loads(stream.readline())
    except (ValueError, OSError) as exc:
        raise RuntimeError('Missing or invalid launcher request. Use npm run start or npm run test.') from exc

    if not isinstance(request, dict):
        raise RuntimeError('Launcher request must be an object.')

    if mode != 'run':
        return None

    lines = request.get('lines')
    if not isinstance(lines, list) or not lines:
        raise RuntimeError('Payload is empty or invalid.')

    for index, line in enumerate(lines, 1):
        if not isinstance(line, str) or not line.strip():
            raise RuntimeError(f'Payload line {index} is empty or invalid.')

        if len(line) + 1 > 254 or any(ch not in ASCII_TO_KEY for ch in line):
            raise RuntimeError(f'Payload line {index} exceeds the chat limit or contains unsupported characters.')

    return lines


def ensure_state_directory():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE.is_symlink() or STATE.stat().st_uid != 0:
        raise RuntimeError(f'{STATE} must be a real directory owned by root.')

    STATE.chmod(0o700)


def stop_session(*_):
    raise KeyboardInterrupt


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
