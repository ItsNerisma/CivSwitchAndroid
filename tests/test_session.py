"""Exercise the privileged lifecycle with fake USB/SELinux, never the real device."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'AndroidSwitch'))
import civswitch as civ


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.selinux = 'Enforcing'
        self.commands = []
        self.usb_error = False
        self.restore_error = False
        self.enforce_error = False
        self.events = []
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        for name, value in [('STATE', self.state), ('BACKUP', self.state / 'usb.json'),
                            ('SESSION', self.state / 'session.json')]:
            self.patches.enter_context(patch.object(civ, name, value))
        self.patches.enter_context(patch.object(civ, 'boot_id', return_value='boot-a'))
        self.patches.enter_context(patch.object(civ.subprocess, 'check_output', side_effect=self.check_output))
        self.patches.enter_context(patch.object(civ.subprocess, 'run', side_effect=self.run_command))
        self.patches.enter_context(patch.object(civ.os, 'geteuid', return_value=0))
        self.patches.enter_context(patch.object(civ, 'ensure_state_directory'))
        self.patches.enter_context(patch.object(civ, 'watch_launcher', return_value=threading.Event()))
        self.patches.enter_context(patch.object(civ, 'wait_connected'))
        self.play = self.patches.enter_context(patch.object(civ, 'play_payload'))
        self.patches.enter_context(patch.object(sys, 'stdout', io.StringIO()))
        owner = self

        class FakeGadget:
            def __init__(self, path=None, backup=None):
                self.snapshot = None
                self.mountpoint = '/fake-usb'

            def prepare(self):
                self.snapshot = {'gadget': '/fake-gadget'}
                civ.atomic_json(civ.BACKUP, self.snapshot)
                owner.events.append('prepare')
                if owner.usb_error:
                    raise RuntimeError('USB preparation failed')

            def bind(self):
                owner.events.append('bind')

            def unbind(self):
                owner.events.append('unbind')

            def restore(self):
                owner.events.append('restore')
                if owner.restore_error:
                    raise RuntimeError('USB restoration failed')
                civ.BACKUP.unlink()

        class FakeHID:
            def __init__(self, *args, **kwargs):
                pass

            def sleep(self, delay):
                pass

            def stop(self):
                owner.events.append('stop')

            def close(self):
                owner.events.append('close')

        self.gadget = self.patches.enter_context(patch.object(civ, 'Gadget', FakeGadget))
        self.patches.enter_context(patch.object(civ, 'FunctionFSHID', FakeHID))

    def check_output(self, command, **kwargs):
        self.assertEqual(command, ['getenforce'])
        return self.selinux + '\n'

    def run_command(self, command, **kwargs):
        self.commands.append(command)
        self.assertEqual(command[0], 'setenforce')
        # The journal must exist before either privileged SELinux change.
        self.assertTrue(civ.SESSION.exists())
        if command[1] == '1' and self.enforce_error:
            raise subprocess.CalledProcessError(1, command)
        self.selinux = 'Enforcing' if command[1] == '1' else 'Permissive'
        return subprocess.CompletedProcess(command, 0)

    def launch(self, mode='test', request=None, options=()):
        with patch.object(sys, 'stdin', io.StringIO(json.dumps(request or {}) + '\n')):
            return civ.main([mode, '--start-delay', '0', *options])

    def assert_restored(self):
        self.assertEqual(self.selinux, 'Enforcing')
        self.assertFalse(civ.SESSION.exists())
        self.assertFalse(civ.BACKUP.exists())

    def test_test_types_only_the_two_messages_and_restores_in_order(self):
        self.assertEqual(self.launch(), 0)
        lines = self.play.call_args.args[1]
        self.assertEqual(lines, ['gezine is a goat', 'Test OK! Run npm start for the full payload'])
        self.assertEqual(self.events, ['prepare', 'bind', 'stop', 'unbind', 'close', 'restore'])
        self.assertEqual(self.commands, [['setenforce', '0'], ['setenforce', '1']])
        self.assert_restored()

    def test_run_receives_the_complete_in_memory_payload(self):
        lines = ['first message', 'second message']
        self.launch('run', {'lines': lines})
        self.assertEqual(self.play.call_args.args[1], lines)
        self.assert_restored()

    def test_initial_permissive_state_stays_permissive(self):
        self.selinux = 'Permissive'
        self.launch()
        self.assertEqual(self.selinux, 'Permissive')
        self.assertEqual(self.commands, [])
        self.assertFalse(civ.SESSION.exists())

    def test_disabled_selinux_is_supported_without_setenforce(self):
        self.selinux = 'Disabled'
        self.launch()
        self.assertEqual(self.commands, [])
        self.assertFalse(civ.SESSION.exists())

    def test_gadget_discovery_failure_still_restores_selinux(self):
        with patch.object(civ, 'Gadget', side_effect=RuntimeError('No gadget')):
            with self.assertRaisesRegex(RuntimeError, 'No gadget'):
                self.launch()
        self.assert_restored()

    def test_partial_usb_preparation_failure_still_restores_both(self):
        self.usb_error = True
        with self.assertRaisesRegex(RuntimeError, 'USB preparation failed'):
            self.launch()
        self.assertIn('restore', self.events)
        self.assert_restored()

    def test_usb_restore_failure_still_enforces_and_retains_recovery_state(self):
        self.restore_error = True
        with self.assertRaisesRegex(RuntimeError, 'USB restoration failed'):
            self.launch()
        self.assertEqual(self.selinux, 'Enforcing')
        self.assertTrue(civ.BACKUP.exists())
        self.assertTrue(civ.SESSION.exists())
        self.restore_error = False
        self.launch('teardown')
        self.assertEqual(self.commands, [['setenforce', '0'], ['setenforce', '1'],
                                        ['setenforce', '0'], ['setenforce', '1']])
        self.assert_restored()

    def test_selinux_restore_failure_can_be_retried_without_usb_backup(self):
        self.enforce_error = True
        with self.assertRaisesRegex(RuntimeError, 'SELinux'):
            self.launch()
        self.assertTrue(civ.SESSION.exists())
        self.assertFalse(civ.BACKUP.exists())
        self.enforce_error = False
        self.launch('teardown')
        self.assert_restored()

    def test_failed_setenforce_zero_never_touches_usb(self):
        with patch.object(civ, 'make_permissive', side_effect=RuntimeError('setenforce failed')):
            with self.assertRaisesRegex(RuntimeError, 'setenforce failed'):
                self.launch()
        self.assertEqual(self.events, [])
        self.assert_restored()

    def test_sigterm_during_playback_cleans_up(self):
        self.play.side_effect = lambda *_: os.kill(os.getpid(), signal.SIGTERM)
        self.assertEqual(self.launch(), 130)
        self.assert_restored()

    def test_repeated_interruptions_are_ignored_during_cleanup(self):
        self.play.side_effect = KeyboardInterrupt
        original = self.gadget.restore

        def interrupt_cleanup(gadget):
            os.kill(os.getpid(), signal.SIGINT)
            os.kill(os.getpid(), signal.SIGTERM)
            original(gadget)

        with patch.object(self.gadget, 'restore', interrupt_cleanup):
            self.assertEqual(self.launch(), 130)
        self.assert_restored()

    def test_invalid_journal_is_kept_and_prevents_a_new_session(self):
        civ.SESSION.write_text('{broken')
        with self.assertRaisesRegex(RuntimeError, 'Invalid session journal'):
            self.launch()
        self.assertEqual(civ.SESSION.read_text(), '{broken')
        self.assertEqual(self.commands, [])

    def test_previous_boot_snapshot_is_discarded_without_changing_current_state(self):
        civ.atomic_json(civ.SESSION, {'boot_id': 'old-boot', 'selinux': 'Permissive'})
        civ.atomic_json(civ.BACKUP, {'gadget': '/old-gadget'})
        self.launch('teardown')
        self.assertEqual(self.events, [])
        self.assertEqual(self.commands, [])
        self.assert_restored()

    def test_pending_session_is_recovered_before_a_new_test(self):
        civ.begin_session()
        civ.atomic_json(civ.BACKUP, {'gadget': '/old-gadget'})
        self.launch()
        self.assertEqual(self.events[0], 'restore')
        self.assert_restored()

    def test_shared_lock_rejects_another_copy_before_changing_selinux(self):
        with open(self.state / 'session.lock', 'a') as lock:
            civ.fcntl.flock(lock, civ.fcntl.LOCK_EX | civ.fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'Another CivSwitch'):
                self.launch()
        self.assertEqual(self.commands, [])
        self.assertFalse(civ.SESSION.exists())

    def test_bad_payload_is_rejected_before_any_privileged_change(self):
        for lines in ([], ['a' * 254], ['hello\nworld'], ['é'], [''], [42]):
            with self.subTest(lines=lines), self.assertRaisesRegex(RuntimeError, 'Payload'):
                self.launch('run', {'lines': lines})
        self.assertEqual(self.commands, [])
        self.assertEqual(self.events, [])

    def test_nonfinite_timeout_is_rejected_before_any_privileged_change(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.launch(options=['--connect-timeout', 'nan'])
        self.assertEqual(self.commands, [])


class ControlPipeTests(unittest.TestCase):
    def test_launcher_eof_requests_cancellation(self):
        read_fd, write_fd = os.pipe()
        try:
            signalled = threading.Event()
            with os.fdopen(read_fd, 'r') as stream, patch.object(civ.os, 'kill', side_effect=lambda *_: signalled.set()) as kill:
                disconnected = civ.watch_launcher(stream)
                self.assertFalse(disconnected.is_set())
                os.close(write_fd)
                write_fd = None
                self.assertTrue(disconnected.wait(2))
                self.assertTrue(signalled.wait(2))
                kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
        finally:
            if write_fd is not None:
                os.close(write_fd)

    def test_eof_in_a_running_python_process_restores_usb_and_selinux(self):
        # Run the actual pipe watcher and lifecycle together in another process.
        # Only hardware calls and root checks are replaced by SessionTests' fakes.
        code = '''
import json, sys, time
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from test_session import SessionTests, civ
watch = civ.watch_launcher
stdout = sys.stdout
phone = SessionTests()
phone.setUp()
def play(*args):
    print('WAITING_FOR_EOF', flush=True)
    time.sleep(30)
phone.play.side_effect = play
try:
    with patch.object(sys, 'stdout', stdout), patch.object(civ, 'watch_launcher', watch):
        status = civ.main(['test', '--start-delay', '0'])
        print(json.dumps({'selinux': phone.selinux, 'events': phone.events,
                          'journal': civ.SESSION.exists(), 'backup': civ.BACKUP.exists()}), flush=True)
finally:
    phone.doCleanups()
sys.exit(status)
'''
        proc = subprocess.Popen([sys.executable, '-u', '-c', code, str(Path(__file__).parent)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            proc.stdin.write('{}\n')
            proc.stdin.flush()
            output = ''
            # The child has a bounded sleep; wait for actual playback before EOF.
            while 'WAITING_FOR_EOF' not in output:
                line = proc.stdout.readline()
                if not line:
                    self.fail('Fake phone stopped before playback: ' + proc.stderr.read())
                output += line
            proc.stdin.close()
            proc.stdin = None
            remaining, errors = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 130, errors)
            final = json.loads(remaining.strip().splitlines()[-1])
            self.assertEqual(final['selinux'], 'Enforcing')
            self.assertIn('restore', final['events'])
            self.assertFalse(final['journal'])
            self.assertFalse(final['backup'])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


if __name__ == '__main__':
    unittest.main()
