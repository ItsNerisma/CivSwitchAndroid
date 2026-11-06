"""Composite Switch gamepad/keyboard implemented through Linux FunctionFS.

Uses the stable FunctionFS v2 and Linux AIO ABIs (no external Python packages).
Endpoint writes must use AIO: O_NONBLOCK alone does not prevent FunctionFS from
waiting for a USB transfer to complete. One outstanding request per endpoint
keeps both interfaces independent and allows unbinding to cancel every request.
"""

from collections import deque
import ctypes as C
import errno
import os
from pathlib import Path
import platform
import select
import struct
import threading
import time

from macro_player import KBD_RELEASED, PAD_NEUTRAL, kbd_report, pad_report


GAMEPAD_DESCRIPTOR = bytes.fromhex(
    '05 01 09 05 a1 01 15 00 25 01 35 00 45 01 75 01 95 10 05 09 19 01 29 10'
    '81 02 05 01 25 07 46 3b 01 75 04 95 01 65 14 09 39 81 42 65 00 95 01 81'
    '01 26 ff 00 46 ff 00 09 30 09 31 09 32 09 35 75 08 95 04 81 02 06 00 ff'
    '09 20 95 01 81 02 0a 21 26 95 08 91 02 c0'
)
KEYBOARD_DESCRIPTOR = bytes.fromhex(
    '05 01 09 06 a1 01 75 01 95 08 05 07 19 e0 29 e7 15 00 25 01 81 02 95 01'
    '75 08 81 01 95 05 75 01 05 08 19 01 29 05 91 02 95 01 75 03 91 01 95 06'
    '75 08 15 00 25 65 05 07 19 00 29 65 81 00 c0'
)
REPORT_DESCRIPTORS = (GAMEPAD_DESCRIPTOR, KEYBOARD_DESCRIPTOR)
EVENT_NAMES = ('BIND', 'UNBIND', 'ENABLE', 'DISABLE', 'SETUP', 'SUSPEND', 'RESUME')
DISCONNECTED = {errno.ENODEV, errno.ESHUTDOWN, errno.ENOTCONN,
                errno.ECONNRESET, errno.ECONNABORTED, errno.EIDRM}


def hid_descriptor(index):
    return struct.pack('<BBHBBBH', 9, 0x21, 0x0111, 0, 1, 0x22,
                       len(REPORT_DESCRIPTORS[index]))


def interface_descriptors(high_speed=False):
    # Switch-compatible interfaces, HID 1.11 and 1 ms polling interval.
    # FunctionFS may remap endpoint addresses to suit the hardware controller.
    interval = 4 if high_speed else 1
    result = bytearray()
    for index, size, addresses in ((0, 64, (0x02, 0x81)),
                                   (1, 8, (0x83, 0x03))):
        result.extend(struct.pack('<9B', 9, 4, index, 0, 2, 3, index, index, 0))
        result.extend(hid_descriptor(index))

        for address in addresses:
            result.extend(struct.pack('<BBBBHB', 7, 5, address, 3, size, interval))

    return bytes(result)


def descriptor_block():
    fs, hs = interface_descriptors(), interface_descriptors(True)
    # v2 magic, total length, HAS_FS_DESC | HAS_HS_DESC, descriptor counts.
    return struct.pack('<5I', 3, 20 + len(fs) + len(hs), 3, 8, 8) + fs + hs


class IOCB(C.Structure):
    _fields_ = [('data', C.c_uint64), ('key', C.c_uint32),
                ('rw_flags', C.c_uint32), ('opcode', C.c_uint16),
                ('priority', C.c_int16), ('fd', C.c_uint32),
                ('buf', C.c_uint64), ('nbytes', C.c_uint64),
                ('offset', C.c_int64), ('reserved', C.c_uint64),
                ('flags', C.c_uint32), ('resfd', C.c_uint32)]


class IOEvent(C.Structure):
    _fields_ = [('data', C.c_uint64), ('obj', C.c_uint64),
                ('result', C.c_int64), ('result2', C.c_int64)]


class LinuxAIO:
    def __init__(self):
        machine = platform.machine().lower()
        if machine in ('aarch64', 'arm64', 'riscv64'):
            numbers = (0, 1, 2, 4)
        elif machine in ('x86_64', 'amd64'):
            numbers = (206, 207, 209, 208)
        elif machine.startswith('arm'):
            numbers = (243, 244, 246, 245)
        elif machine in ('i386', 'i686'):
            numbers = (245, 246, 248, 247)
        else:
            raise RuntimeError(f'Linux AIO syscall numbers unknown for {machine}')

        self.numbers = dict(zip(('setup', 'destroy', 'submit', 'getevents'), numbers))
        self.libc = C.CDLL(None, use_errno=True)
        self.libc.syscall.restype = C.c_long
        self.context = C.c_ulong(0)
        self.events = (IOEvent * 4)()
        self.call('setup', C.c_uint(4), C.byref(self.context))

    def call(self, name, *args):
        result = self.libc.syscall(C.c_long(self.numbers[name]), *args)
        if result == -1:
            code = C.get_errno()
            raise OSError(code, f'io_{name}: {os.strerror(code)}')

        return result

    def submit(self, request):
        pointers = (C.POINTER(IOCB) * 1)(C.pointer(request))
        if self.call('submit', self.context, C.c_long(1), pointers) != 1:
            raise RuntimeError('io_submit did not accept the endpoint request')

    def reap(self):
        count = self.call('getevents', self.context, C.c_long(0), C.c_long(4),
                          self.events, C.c_void_p())
        return [(self.events[i].data, self.events[i].result) for i in range(count)]

    def close(self):
        if self.context.value:
            self.call('destroy', self.context)
            self.context.value = 0


class FunctionFSHID:
    def __init__(self, mountpoint, trace=False):
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._enabled = False
        self._reopen = [False] * 4
        self._reports = [PAD_NEUTRAL, KBD_RELEASED]
        self._versions = [0, 0]
        self._completed_versions = [-1, -1]
        self._counts = [0, 0]
        self._write_errors = ['', '']
        self._idle = [0, 0]
        self._protocol = [1, 1]
        self._outputs = [bytes(8), bytes(1)]
        self._echo = deque(maxlen=16)
        self._error = None
        self._trace = trace
        self._ep0 = None
        self._fds = []
        self._aio = None
        self._thread = None
        self._pending = [False] * 4
        self._sent_versions = [None] * 4
        self._buffers = [C.create_string_buffer(64) for _ in range(4)]
        self._requests = []

        root = Path(mountpoint)
        self._root = root

        try:
            self._ep0 = os.open(root / 'ep0', os.O_RDWR | os.O_NONBLOCK)
            for block in (descriptor_block(), struct.pack('<4I', 2, 16, 0, 0)):
                if os.write(self._ep0, block) != len(block):
                    raise RuntimeError('Short write registering FunctionFS descriptors')

            # ep1=gamepad OUT, ep2=gamepad IN, ep3=keyboard IN, ep4=keyboard OUT.
            for slot in range(4):
                fd = os.open(root / f'ep{slot + 1}', os.O_RDWR | os.O_NONBLOCK)
                self._fds.append(fd)
                request = IOCB()
                request.data = slot
                request.fd = fd
                request.opcode = 1 if slot in (1, 2) else 0  # PWRITE / PREAD
                request.buf = C.addressof(self._buffers[slot])
                request.nbytes = 8 if slot in (2, 3) else 64
                self._requests.append(request)

            self._aio = LinuxAIO()
            self._thread = threading.Thread(target=self._pump, daemon=True)
            self._thread.start()
        except BaseException:
            self.close()
            raise

    def _output(self, index, data):
        self._outputs[index] = data

        # Echo gamepad output reports; keyboard output is LEDs.
        if index == 0 and data:
            self._echo.append(data[:64])

    def _stall(self, request_type):
        try:
            # An operation opposite to the SETUP direction stalls ep0.
            if request_type & 0x80:
                os.read(self._ep0, 0)
            else:
                os.write(self._ep0, b'')
        except OSError as exc:
            if exc.errno != errno.EL2HLT:
                raise

    def _setup(self, packet):
        kind, request, value, index, length = struct.unpack('<BBHHH', packet)
        if self._trace:
            print(f'USB SETUP: type={kind:02x} request={request:02x} '
                  f'value={value:04x} interface={index} length={length}', flush=True)

        if index not in (0, 1):
            self._stall(kind)
            return

        reply = None
        if kind == 0x81 and request == 6:
            if value == 0x2200:
                reply = REPORT_DESCRIPTORS[index]
            elif value == 0x2100:
                reply = hid_descriptor(index)
        elif kind == 0xa1 and request == 1 and value & 0xff == 0:
            if value >> 8 == 1:
                with self._condition:
                    reply = self._reports[index]
            elif value >> 8 == 2:
                reply = self._outputs[index]
        elif kind == 0xa1 and request == 2:
            reply = bytes([self._idle[index]])
        elif kind == 0xa1 and request == 3 and index == 1:
            reply = bytes([self._protocol[index]])
        elif kind == 0x21:
            if request == 9 and value >> 8 == 2 and value & 0xff == 0 and length <= 64:
                self._output(index, os.read(self._ep0, length))
                return

            if request == 10 and value & 0xff == 0 and length == 0:
                self._idle[index] = value >> 8
                os.read(self._ep0, 0)
                return

            if request == 11 and index == 1 and value in (0, 1) and length == 0:
                self._protocol[index] = value
                os.read(self._ep0, 0)
                return

        if reply is None:
            self._stall(kind)
        else:
            os.write(self._ep0, reply[:length])

    def _events(self):
        if not select.select([self._ep0], [], [], .002)[0]:
            return

        try:
            events = os.read(self._ep0, 48)
            if not events or len(events) % 12:
                raise RuntimeError('Invalid FunctionFS event stream')

            for offset in range(0, len(events), 12):
                event = events[offset + 8]
                if event == 4:
                    self._setup(events[offset:offset + 8])
                elif event == 2:
                    self._enabled = True
                    self._reopen = [True] * 4
                    print('FunctionFS: both HID interfaces enabled.', flush=True)
                elif event in (1, 3):
                    self._enabled = False
                    self._reopen = [True] * 4
                    self._echo.clear()
                    with self._condition:
                        self._counts = [0, 0]
                        self._completed_versions = [-1, -1]

                if self._trace and event != 4:
                    name = EVENT_NAMES[event] if event < len(EVENT_NAMES) else str(event)
                    print(f'FunctionFS: {name}', flush=True)
        except OSError as exc:
            if exc.errno not in DISCONNECTED | {errno.EAGAIN, errno.EINTR}:
                raise

    def _completions(self):
        for slot, result in self._aio.reap():
            self._pending[slot] = False
            index = 0 if slot < 2 else 1
            if result < 0:
                code = -result
                if code not in DISCONNECTED | {errno.EAGAIN, errno.EINTR}:
                    raise OSError(code, f'FunctionFS ep{slot + 1}: {os.strerror(code)}')

                if slot in (1, 2):
                    with self._condition:
                        self._write_errors[index] = errno.errorcode.get(code, str(code))

                if code == errno.ENODEV:
                    self._reopen[slot] = True
            elif slot in (1, 2):
                if result != self._requests[slot].nbytes:
                    raise RuntimeError(f'FunctionFS ep{slot + 1}: short transfer '
                                       f'{result}/{self._requests[slot].nbytes}')

                with self._condition:
                    self._counts[index] += 1
                    self._write_errors[index] = ''
                    version = self._sent_versions[slot]
                    if version is not None:
                        self._completed_versions[index] = version

                    self._condition.notify_all()
            else:
                self._output(index, self._buffers[slot].raw[:result])

    def _submit(self):
        for slot, request in enumerate(self._requests):
            if self._pending[slot]:
                continue

            if self._reopen[slot] and not self._reopen_endpoint(slot):
                continue

            if slot in (1, 2):
                index = slot - 1
                with self._condition:
                    report = self._reports[index]
                    version = self._versions[index]

                if slot == 1 and self._echo:
                    report, version = self._echo.popleft(), None

                C.memmove(request.buf, report, len(report))
                request.nbytes = len(report)
                self._sent_versions[slot] = version

            try:
                self._aio.submit(request)
                self._pending[slot] = True
            except OSError as exc:
                if exc.errno not in DISCONNECTED | {errno.EAGAIN, errno.EINTR}:
                    raise

                if exc.errno == errno.ENODEV:
                    self._reopen[slot] = True

    def _reopen_endpoint(self, slot):
        # Some kernels latch an endpoint error on DISABLE (including when
        # SET_INTERFACE re-enables a composite function). Only open() clears it.
        # Reopen only an endpoint whose own AIO request has completed. An OUT
        # request on another endpoint can legitimately stay pending indefinitely.
        if self._fds[slot] is not None:
            os.close(self._fds[slot])
            self._fds[slot] = None

        try:
            fd = os.open(self._root / f'ep{slot + 1}', os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno not in (errno.EBUSY, errno.ENODEV, errno.EAGAIN):
                raise

            return False

        self._fds[slot] = fd
        self._requests[slot].fd = fd
        self._reopen[slot] = False
        return True

    def _pump(self):
        try:
            while not self._stop.is_set():
                self._events()
                self._completions()

                if self._enabled:
                    self._submit()
        except BaseException as exc:
            with self._condition:
                self._error = exc
                self._condition.notify_all()

    def check(self):
        with self._condition:
            if self._error is not None:
                raise RuntimeError(f'FunctionFS transport failed: {self._error}') from self._error

    def counts(self):
        with self._condition:
            return tuple(self._counts)

    def write_errors(self):
        with self._condition:
            return tuple(self._write_errors)

    def _set(self, index, report, timeout=3):
        with self._condition:
            self.check()
            self._versions[index] += 1
            version = self._versions[index]
            self._reports[index] = report
            ready = self._condition.wait_for(
                lambda: self._completed_versions[index] >= version or self._error is not None,
                timeout)
            self.check()

            if not ready:
                raise RuntimeError(f'Host stopped consuming HID interface {index}')

    def send_kbd(self, modifier=0, key=0):
        self._set(1, kbd_report(modifier, key))

    def send_pad(self, *args, **kwargs):
        self._set(0, pad_report(*args, **kwargs))

    def release_kbd(self):
        self.send_kbd()

    def release_pad(self):
        self.send_pad()

    def release_all(self):
        self.release_kbd()
        self.release_pad()

    def sleep(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check()
            self._stop.wait(min(.05, max(0, deadline - time.monotonic())))

        self.check()

    def stop(self):
        # Main must unbind USB before close(), to cancel outstanding USB I/O.
        self._stop.set()

    def close(self):
        self.stop()

        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError('FunctionFS worker still blocked; unbind USB before closing')

        if self._aio is not None:
            self._aio.close()
            self._aio = None

        for fd in self._fds:
            if fd is not None:
                os.close(fd)

        self._fds.clear()

        if self._ep0 is not None:
            os.close(self._ep0)
            self._ep0 = None
