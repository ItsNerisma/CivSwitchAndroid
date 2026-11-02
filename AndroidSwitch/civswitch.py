#!/usr/bin/env python3
"""Own the Android USB gadget and HID transport for the entire session."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from functionfs import FunctionFSHID
from macro_player import play_payload

BASE = Path(__file__).resolve().parent
BACKUP = BASE / '.gadget_backup.json'
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


def write_once(path, data):
    """ConfigFS replaces attributes per syscall, including binary descriptors."""
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
            print('WARNING: Stale backup found. Restoring first...', flush=True)
            # A failed restoration must keep the only copy of Android's state.
            self.restore()
            self.path = find_gadget()
            self.config = self.configuration()
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
        temp = self.backup.with_suffix('.tmp')
        with open(temp, 'w', encoding='utf-8') as f:
            os.chmod(temp, 0o600)
            json.dump(snapshot, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, self.backup)
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
            self.unbind()
            self.clear_links()
            if mounted(self.mountpoint):
                subprocess.run(['umount', str(self.mountpoint)], check=True)
            function = self.path / 'functions' / snapshot['function']
            if function.exists():
                function.rmdir()
            if not snapshot['mountpoint_existed'] and self.mountpoint.exists():
                self.mountpoint.rmdir()
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


def stop_session(*_):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('test', 'run', 'teardown'))
    parser.add_argument('payload', nargs='?', default=str(BASE / 'payload.txt'))
    parser.add_argument('--start-delay', '--delay', type=float, default=2)
    parser.add_argument('--connect-timeout', type=float, default=90)
    parser.add_argument('--usb-trace', action='store_true', help='Log USB control requests.')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error('Run as root in Termux (su).')
    if args.start_delay < 0 or args.connect_timeout <= 0:
        parser.error('Delays must be nonnegative and connection timeout positive.')
    lines = None
    if args.mode == 'run':
        lines = [line for line in Path(args.payload).read_text().splitlines() if line.strip()]
        if not lines:
            parser.error('Payload is empty.')
    # One owner for configuration, reports and restoration.
    with open(BASE / '.session.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another CivSwitch session is running. Stop it first.')
        signal.signal(signal.SIGTERM, stop_session)
        if args.mode == 'teardown':
            if BACKUP.exists():
                Gadget(path=json.loads(BACKUP.read_text())['gadget']).restore()
            else:
                print('No USB session to restore.')
            return
        gadget = Gadget()
        hid = None
        try:
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
                'Test OK! Run run.sh for the full payload',
            ])
            hid.sleep(.1)
        except KeyboardInterrupt:
            print('\nSession stopped.', flush=True)
        finally:
            # Unbinding cancels endpoint requests before their AIO context and
            # buffers are freed. Closing a descriptor alone cannot cancel I/O.
            try:
                if hid is not None:
                    hid.stop()
                if gadget.snapshot is not None:
                    gadget.unbind()
            finally:
                try:
                    if hid is not None:
                        hid.close()
                finally:
                    if gadget.snapshot is not None:
                        gadget.restore()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
