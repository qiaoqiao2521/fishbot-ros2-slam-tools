"""Real bounded file IO and failure injection; no ROS, service, or physics startup."""
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from tools.cooperation_recording import BoundedDiagnosticLog


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now


class FailingStream:
    def __init__(self, stream, operation):
        self.stream, self.operation = stream, operation

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def write(self, value):
        if self.operation == 'write':
            raise OSError(errno.ENOSPC, 'injected disk full')
        return self.stream.write(value)

    def flush(self):
        if self.operation == 'flush':
            raise OSError(errno.ENOSPC, 'injected disk full')
        return self.stream.flush()


class BoundedDiagnosticLogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'physics-diagnostic.jsonl'
        self.clock = Clock()

    def logger(self, **options):
        value = BoundedDiagnosticLog(self.path, clock=self.clock, **options)
        self.addCleanup(value.close)
        return value

    def rows(self, backups):
        paths = [Path(f'{self.path}.{index}') for index in range(backups, 0, -1)]+[self.path]
        result = []
        for path in paths:
            if path.exists():
                raw = path.read_bytes()
                self.assertTrue(raw.isascii())
                if raw:
                    self.assertTrue(raw.endswith(b'\n'))
                result.extend(json.loads(row) for row in raw.splitlines())
        return result

    def test_default_capacity_and_lossy_evidence_label(self):
        writer = self.logger()
        status = writer.snapshot()
        self.assertEqual(status['kind'], 'rolling_diagnostic')
        self.assertTrue(status['not_complete_evidence'])
        self.assertFalse(status['complete_evidence'])
        self.assertEqual(status['retained_upper_bound_bytes'], 32*1024*1024)
        self.assertEqual(status['max_retained_parts'], 4)
        self.assertEqual(status['hz_wall'], 2.)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertIsNone(status['error'])

    def test_real_rotations_bound_every_part_and_total_bytes(self):
        writer = self.logger(hz=50, max_bytes=1024, backups=3)
        for index in range(100):
            self.clock.now = float(index)
            self.assertTrue(writer.offer(json.dumps({'sequence': index, 'stamp': index*.02,
                                                    'padding': 'x'*230}, separators=(',', ':'))))
        writer.close()
        parts = list(Path(self.directory.name).glob(self.path.name+'*'))
        self.assertEqual(len(parts), 4)
        self.assertTrue(all(path.stat().st_size <= 1024 for path in parts))
        self.assertLessEqual(sum(path.stat().st_size for path in parts), 4*1024)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in parts))
        rows = self.rows(3)
        sequences = [row['sequence'] for row in rows]
        self.assertEqual(sequences, list(range(sequences[0], 100)))
        self.assertGreater(sequences[0], 0)
        status = writer.snapshot()
        self.assertEqual(status['recorded'], 100)
        self.assertGreater(status['rotations'], 3)
        self.assertGreater(status['overwritten_parts'], 0)
        self.assertIsNone(status['error'])

    def test_wall_clock_limit_never_queues_or_catches_up_old_offers(self):
        writer = self.logger()
        original = json.dumps({'sequence': 10, 'stamp': .02, 'episode': 'original'})
        self.assertTrue(writer.offer(original))
        for index in range(11, 20):
            self.clock.now = .49
            self.assertFalse(writer.offer(json.dumps({'sequence': index, 'stamp': .02})))
        self.clock.now = .5
        self.assertTrue(writer.offer(json.dumps({'sequence': 20, 'stamp': .04})))
        self.clock.now = 100.
        self.assertTrue(writer.offer(json.dumps({'sequence': 999, 'stamp': .001})))
        self.assertFalse(writer.offer(json.dumps({'sequence': 1000, 'stamp': .002})))
        rows = self.rows(3)
        self.assertEqual([row['sequence'] for row in rows], [10, 20, 999])
        self.assertEqual(rows[2]['stamp'], .001)
        self.assertEqual(self.path.read_text().splitlines()[0], original)
        self.assertEqual(writer.snapshot()['skipped_rate_limit'], 10)

    def test_source_and_ascii_escaped_strings_are_unchanged(self):
        writer = self.logger()
        text = json.dumps({'sequence': 47, 'stamp': 1234.56789, 'label': '小鱼',
                           'source': {'episode_id': 'same-episode'}})
        self.assertTrue(writer.offer(text))
        self.assertEqual(self.path.read_bytes(), text.encode('ascii')+b'\n')
        self.assertEqual(self.rows(3)[0]['label'], '小鱼')

    def test_existing_base_is_not_overwritten_or_appended(self):
        self.path.write_bytes(b'historical evidence\n')
        with self.assertRaises(FileExistsError):
            self.logger()
        self.assertEqual(self.path.read_bytes(), b'historical evidence\n')
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])

    def test_every_planned_existing_sidecar_is_preserved_with_new_probes_removed(self):
        for index in (1, 2, 3):
            with self.subTest(index=index):
                path = self.path.parent/f'case-{index}.jsonl'
                sidecar = Path(f'{path}.{index}')
                sidecar.write_bytes(b'old sidecar\n')
                with self.assertRaises(FileExistsError):
                    BoundedDiagnosticLog(path, clock=self.clock)
                self.assertEqual(sidecar.read_bytes(), b'old sidecar\n')
                self.assertFalse(path.exists())
                for other in set((1, 2, 3))-{index}:
                    self.assertFalse(Path(f'{path}.{other}').exists())

    def test_dangling_symlinks_are_existing_history_not_followed(self):
        for name in (self.path, Path(f'{self.path}.1')):
            with self.subTest(name=name.name):
                target = self.path.parent/f'absent-{name.name}'
                name.symlink_to(target)
                with self.assertRaises(FileExistsError):
                    self.logger()
                self.assertTrue(name.is_symlink())
                self.assertFalse(target.exists())
                name.unlink()  # Test-owned fixture only.

    def test_file_modes_are_0600_even_under_restrictive_umask(self):
        previous = os.umask(0o777)
        try:
            writer = self.logger(max_bytes=1024, backups=1)
            self.assertTrue(writer.offer(json.dumps({'pad': 'x'*900})))
            self.clock.now = 1.
            self.assertTrue(writer.offer(json.dumps({'pad': 'y'*900})))
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(f'{self.path}.1').stat().st_mode), 0o600)

    def test_oversize_record_disables_once_and_remains_visible_after_close(self):
        writer = self.logger(max_bytes=1024, backups=1)
        self.assertFalse(writer.offer(json.dumps({'pad': 'x'*1024})))
        status = writer.snapshot()
        self.assertFalse(status['enabled'])
        self.assertEqual(status['oversize_rejections'], 1)
        self.assertEqual(status['recorded'], 0)
        self.assertEqual(status['error_code'], 'oversize_record')
        self.assertIn('1024', status['error'])
        self.assertFalse(writer.offer('{}'))
        self.assertEqual(writer.snapshot()['skipped_disabled'], 1)
        writer.close()
        self.assertEqual(writer.snapshot()['error'], status['error'])
        self.assertEqual(self.path.stat().st_size, 0)

    def test_exact_part_size_including_terminator_is_allowed_but_never_exceeded(self):
        writer = self.logger(max_bytes=1024, backups=1)
        self.assertTrue(writer.offer('"'+'x'*1021+'"'))
        self.assertEqual(self.path.stat().st_size, 1024)
        self.clock.now = 1.
        self.assertTrue(writer.offer('{}'))
        self.assertEqual(Path(f'{self.path}.1').stat().st_size, 1024)
        self.assertLessEqual(sum(p.stat().st_size for p in self.path.parent.iterdir()), 2048)
        self.assertEqual(self.rows(1), ['x'*1021, {}])

    def test_malformed_nonascii_and_multiline_values_never_become_disk_records(self):
        for index, value in enumerate((None, b'{}', '{', 'NaN', '{"x":Infinity}',
                                       '{"x":"小鱼"}', '{}\n{}', '{}\r', '[]\n')):
            with self.subTest(value=value):
                writer = BoundedDiagnosticLog(self.path.parent/f'invalid-{index}', clock=self.clock)
                try:
                    self.assertFalse(writer.offer(value))
                    self.assertEqual(writer.snapshot()['invalid_rejections'], 1)
                    self.assertEqual(writer.snapshot()['error_code'], 'invalid_record')
                    self.assertFalse(writer.snapshot()['enabled'])
                finally:
                    writer.close()

    def test_write_and_flush_errors_disable_diagnostics_without_stderr_storm_or_raise(self):
        for operation in ('write', 'flush'):
            with self.subTest(operation=operation):
                writer = BoundedDiagnosticLog(self.path.parent/f'failure-{operation}', clock=self.clock)
                writer.handler.stream = FailingStream(writer.handler.stream, operation)
                errors = io.StringIO()
                try:
                    with contextlib.redirect_stderr(errors):
                        self.assertFalse(writer.offer('{}'))
                        self.assertFalse(writer.offer('{}'))
                        writer.close()
                    status = writer.snapshot()
                    self.assertEqual(status['error_code'], 'write_failed')
                    self.assertIn('injected disk full', status['error'])
                    self.assertFalse(status['enabled'])
                    self.assertTrue(status['closed'])
                    self.assertEqual(status['recorded'], 0)
                    self.assertEqual(status['skipped_disabled'], 1)
                    self.assertEqual(errors.getvalue(), '')
                finally:
                    writer.close()

    def test_rollover_failure_is_visible_without_overwriting_existing_bytes(self):
        writer = self.logger(max_bytes=1024, backups=1)
        self.assertTrue(writer.offer(json.dumps({'padding': 'x'*900})))
        before = self.path.read_bytes()
        self.clock.now = 1.
        with patch.object(writer.handler, 'rotate', side_effect=OSError(errno.ENOSPC, 'rename full')):
            self.assertFalse(writer.offer(json.dumps({'padding': 'y'*900})))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn('rename full', writer.snapshot()['error'])
        self.assertEqual(writer.snapshot()['recorded'], 1)

    def test_close_failure_is_visible_and_close_is_idempotent(self):
        writer = self.logger()
        original = writer.handler.close
        with patch.object(writer.handler, 'close', side_effect=OSError('close fault')) as close:
            writer.close(); writer.close()
            self.assertEqual(close.call_count, 1)
        original()
        status = writer.snapshot()
        self.assertTrue(status['closed'])
        self.assertFalse(status['enabled'])
        self.assertEqual(status['error_code'], 'close_failed')
        self.assertIn('close fault', status['error'])
        self.assertFalse(writer.offer('{}'))
        self.assertEqual(writer.snapshot()['skipped_closed'], 1)

    def test_clock_errors_and_rollback_are_visible_without_rewriting_source_time(self):
        for index, value in enumerate((float('nan'), float('inf'), -1., True)):
            with self.subTest(value=value):
                writer = BoundedDiagnosticLog(self.path.parent/f'clock-{index}', clock=lambda: value)
                try:
                    self.assertFalse(writer.offer('{"stamp":1}'))
                    self.assertEqual(writer.snapshot()['error_code'], 'clock_failed')
                finally:
                    writer.close()
        writer = self.logger()
        self.clock.now = 10.
        self.assertTrue(writer.offer('{"stamp":1}'))
        self.clock.now = 9.
        self.assertFalse(writer.offer('{"stamp":2}'))
        self.assertEqual(writer.snapshot()['error_code'], 'clock_failed')
        self.assertEqual(self.rows(3), [{'stamp': 1}])

    def test_constructor_rejects_unbounded_or_invalid_options_before_file_creation(self):
        for options in ({'hz': True}, {'hz': float('nan')}, {'hz': float('inf')}, {'hz': .09},
                        {'hz': 50.01}, {'hz': '2'}, {'hz': 10**1000}, {'max_bytes': True}, {'max_bytes': 1023},
                        {'max_bytes': 64*1024*1024+1}, {'max_bytes': 1024.}, {'backups': 0},
                        {'backups': 8}, {'backups': True}, {'backups': 1.5}, {'clock': None}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                BoundedDiagnosticLog(self.path, **options)
        self.assertFalse(self.path.exists())

    def test_permission_setup_failure_removes_only_new_probe_and_closes_descriptor(self):
        descriptors = []
        original_open = os.open
        def tracked_open(*args, **kwargs):
            descriptor = original_open(*args, **kwargs)
            descriptors.append(descriptor)
            return descriptor
        with patch('tools.cooperation_recording.os.open', side_effect=tracked_open), patch(
                'tools.cooperation_recording.os.fchmod', side_effect=OSError('chmod fault')):
            with self.assertRaisesRegex(OSError, 'chmod fault'):
                self.logger()
        self.assertFalse(self.path.exists())
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_parser_recursion_failure_is_visible_without_escaping_the_writer(self):
        writer = self.logger(max_bytes=8192)
        with patch('tools.cooperation_recording.json.loads', side_effect=RecursionError('parser limit')):
            self.assertFalse(writer.offer('{}'))
        self.assertEqual(writer.snapshot()['error_code'], 'invalid_record')
        self.assertIn('RecursionError', writer.snapshot()['error'])

    def test_allowed_configuration_boundaries_remain_bounded(self):
        for index, (hz, maximum, backups) in enumerate(((.1, 1024, 1), (50, 64*1024*1024, 7))):
            with self.subTest(hz=hz, maximum=maximum, backups=backups):
                writer = BoundedDiagnosticLog(self.path.parent/f'boundary-{index}', hz, maximum, backups, self.clock)
                try:
                    self.assertTrue(writer.offer('{}'))
                    self.assertEqual(writer.snapshot()['retained_upper_bound_bytes'], maximum*(backups+1))
                finally:
                    writer.close()


if __name__ == '__main__':
    unittest.main()
