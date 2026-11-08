"""Characterize hot private writes without changing either document's schema."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('private_json_installer', Path(__file__).parents[1] / 'install_helper.py')
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PrivateJsonTests(unittest.TestCase):
    writers = (
        ('hot_record_write', 'hot-transaction.json', {'protocol': 1, 'phase': 'prepared', 'before': {'中文': True}}),
        ('hot_owned_write', 'hot-owned.json', {'protocol': 1, 'files': {}, 'current': None, 'previous': None}),
    )

    def test_target_bytes_mode_and_order(self):
        for writer, filename, value in self.writers:
            with self.subTest(writer=writer), tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                events = []
                with patch.object(m, 'STATE', state), \
                        patch.object(m, 'safe_path', side_effect=lambda *args: events.append(('safe', args))), \
                        patch.object(m, 'atomic_write', side_effect=lambda *args: events.append(('atomic', args))), \
                        patch.object(m, 'hot_sync', side_effect=lambda: events.append(('sync',))):
                    self.assertIsNone(getattr(m, writer)(value))
                self.assertEqual(events, [
                    ('safe', (state, True)),
                    ('atomic', (state / filename, json.dumps(value).encode(), 0o600)),
                    ('sync',),
                ])

    def test_failures_propagate_without_later_operations(self):
        for writer, _, value in self.writers:
            for failing_stage in ('safe_path', 'atomic_write', 'hot_sync'):
                with self.subTest(writer=writer, stage=failing_stage):
                    error = OSError('injected ' + failing_stage)
                    with patch.object(m, 'safe_path') as safe, \
                            patch.object(m, 'atomic_write') as atomic, \
                            patch.object(m, 'hot_sync') as sync:
                        stages = (safe, atomic, sync)
                        index = ('safe_path', 'atomic_write', 'hot_sync').index(failing_stage)
                        stages[index].side_effect = error
                        with self.assertRaises(OSError) as raised:
                            getattr(m, writer)(value)
                        self.assertIs(raised.exception, error)
                        self.assertEqual([stage.call_count for stage in stages],
                                         [1 if i <= index else 0 for i in range(3)])

    def test_real_atomic_write_and_directory_fsync_failure(self):
        for writer, filename, value in self.writers:
            for fail_directory_sync in (False, True):
                with self.subTest(writer=writer, fail_directory_sync=fail_directory_sync), \
                        tempfile.TemporaryDirectory() as directory:
                    state = Path(directory)
                    target = state / filename
                    target.write_bytes(b'previous contents')
                    target.chmod(0o644)
                    real_fsync = os.fsync
                    synced = []
                    error = OSError('directory fsync failed')

                    def fsync(fd):
                        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
                        synced.append(is_directory)
                        if is_directory and fail_directory_sync:
                            raise error
                        return real_fsync(fd)

                    with patch.object(m, 'STATE', state), patch.object(m, 'safe_path'), \
                            patch.object(m.os, 'fsync', side_effect=fsync), \
                            patch.object(m.os, 'close', wraps=os.close) as close:
                        if fail_directory_sync:
                            with self.assertRaises(OSError) as raised:
                                getattr(m, writer)(value)
                            self.assertIs(raised.exception, error)
                        else:
                            getattr(m, writer)(value)
                        close.assert_called_once()
                    self.assertEqual(synced, [False, True])
                    self.assertEqual(target.read_bytes(), json.dumps(value).encode())
                    self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                    self.assertEqual(list(state.iterdir()), [target])


if __name__ == '__main__':
    unittest.main()
