"""Bounded rolling diagnostics, deliberately separate from complete acceptance evidence."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import threading
import time


class _VisibleRotatingHandler(RotatingFileHandler):
    """Keep stdlib rollover; report IO failures to the owner's wrapper once."""
    def __init__(self, path, max_bytes, backups):
        self.rotations = 0
        self.overwritten_parts = 0
        super().__init__(path, mode='a', maxBytes=max_bytes, backupCount=backups,
                         encoding='ascii', delay=True, errors='strict')
        self.setFormatter(logging.Formatter('%(message)s'))

    def _open(self):
        # The first file is reserved by the owner. After rollover this path must
        # be absent; never append an unexpectedly replaced/new historical file.
        descriptor, _ = _exclusive_descriptor(Path(self.baseFilename))
        return os.fdopen(descriptor, 'a', encoding='ascii', errors='strict', newline='\n')

    def doRollover(self):
        oldest = Path(self.rotation_filename(f'{self.baseFilename}.{self.backupCount}'))
        try:
            evicts_data = oldest.stat().st_size > 0
        except FileNotFoundError:
            evicts_data = False
        super().doRollover()
        self.rotations += 1
        self.overwritten_parts += int(evicts_data)

    def handleError(self, record):
        # BaseRotatingHandler.emit catches write/flush/rename failures here.
        # Re-raise to the bounded wrapper, without logging's stderr traceback.
        raise


def _unlink_owned(path, identity):
    try:
        current = path.lstat()
        if (current.st_dev, current.st_ino) == identity:
            path.unlink()
    except FileNotFoundError:
        pass


def _exclusive_descriptor(path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    identity = None
    try:
        info = os.fstat(descriptor)
        identity = info.st_dev, info.st_ino
        os.fchmod(descriptor, 0o600)
        return descriptor, identity
    except BaseException:
        os.close(descriptor)
        if identity is not None:
            _unlink_owned(path, identity)
        raise


def _reserve_paths(path, backups):
    """O_EXCL-probe every planned name; remove only this call's empty probes."""
    reserved = []
    base_descriptor = None
    try:
        for index in range(backups+1):
            name = path if index == 0 else Path(f'{path}.{index}')
            descriptor, identity = _exclusive_descriptor(name)
            reserved.append((name, identity))
            if index == 0:
                base_descriptor = descriptor
            else:
                os.close(descriptor)
        for name, identity in reserved[1:]:
            _unlink_owned(name, identity)
        return base_descriptor, reserved[0][1]
    except BaseException:
        if base_descriptor is not None:
            os.close(base_descriptor)
        for name, identity in reversed(reserved):
            _unlink_owned(name, identity)
        raise


def _reject_json_constant(value):
    raise ValueError(f'non-JSON constant {value}')


class BoundedDiagnosticLog:
    """Latest-offer wall-clock sampling plus stdlib byte-bounded file rotation.

    This is lossy rolling diagnostic storage. Source JSON is never restamped,
    transformed or queued, and these files are not complete acceptance evidence.
    Constructor configuration/open errors reject startup; runtime recording errors
    disable only this writer and remain observable in snapshot().
    """
    def __init__(self, path, hz=2, max_bytes=8*1024*1024, backups=3, clock=time.monotonic):
        if (isinstance(hz, bool) or not isinstance(hz, (int, float))
                or not .1 <= hz <= 50 or not math.isfinite(hz)):
            raise ValueError('hz must be finite and between 0.1 and 50')
        if type(max_bytes) is not int or not 1024 <= max_bytes <= 64*1024*1024:
            raise ValueError('max_bytes must be an integer from 1 KiB to 64 MiB')
        if type(backups) is not int or not 1 <= backups <= 7:
            raise ValueError('backups must be an integer from 1 to 7; zero disables bounded rollover')
        if not callable(clock):
            raise ValueError('clock must be callable')
        self.path = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hz, self.max_bytes, self.backups = float(hz), max_bytes, backups
        self.clock = clock
        self.lock = threading.RLock()
        self.enabled, self.closed = True, False
        self.error = self.error_code = self.close_error = None
        self.offered = self.recorded = self.skipped_rate_limit = 0
        self.skipped_disabled = self.skipped_closed = 0
        self.oversize_rejections = self.invalid_rejections = 0
        self.bytes_written = 0
        self.next_write = self.last_offer_monotonic = self.last_written_monotonic = None
        descriptor, identity = _reserve_paths(self.path, backups)
        try:
            self.handler = _VisibleRotatingHandler(self.path, max_bytes, backups)
            self.handler.stream = os.fdopen(descriptor, 'a', encoding='ascii', errors='strict', newline='\n')
        except BaseException:
            os.close(descriptor)
            _unlink_owned(self.path, identity)
            raise

    def _close_handler(self):
        try:
            self.handler.close()
        except Exception as error:
            self.close_error = f'{type(error).__name__}: {error}'
            if self.error is None:
                self.error_code, self.error = 'close_failed', self.close_error

    def _disable(self, code, error):
        self.enabled = False
        if self.error is None:
            self.error_code, self.error = code, str(error)
        self._close_handler()

    def offer(self, serialized_json) -> bool:
        with self.lock:
            self.offered += 1
            if self.closed:
                self.skipped_closed += 1
                return False
            if not self.enabled:
                self.skipped_disabled += 1
                return False
            if (not isinstance(serialized_json, str) or not serialized_json.isascii()
                    or '\n' in serialized_json or '\r' in serialized_json):
                self.invalid_rejections += 1
                self._disable('invalid_record', 'record must be one line of ASCII JSON without a terminator')
                return False
            size = len(serialized_json)+1  # ASCII plus the handler's single newline.
            if size > self.max_bytes:
                self.oversize_rejections += 1
                self._disable('oversize_record', f'record is {size} bytes; part limit is {self.max_bytes}')
                return False
            try:
                now = self.clock()
                if (isinstance(now, bool) or not isinstance(now, (int, float))
                        or not math.isfinite(now) or now < 0
                        or self.last_offer_monotonic is not None and now < self.last_offer_monotonic):
                    raise ValueError('diagnostic wall clock must be finite, nonnegative and monotonic')
                self.last_offer_monotonic = now
            except Exception as error:
                self._disable('clock_failed', f'{type(error).__name__}: {error}')
                return False
            if self.next_write is not None and now < self.next_write:
                self.skipped_rate_limit += 1
                return False
            try:
                json.loads(serialized_json, parse_constant=_reject_json_constant)
            except (ValueError, RecursionError) as error:
                self.invalid_rejections += 1
                self._disable('invalid_record', f'{type(error).__name__}: {error}')
                return False
            record = logging.LogRecord('fishbot.cooperation.diagnostic', logging.INFO,
                                       __file__, 0, serialized_json, (), None)
            try:
                self.handler.handle(record)  # emit writes and flushes; failures propagate through handleError.
            except Exception as error:
                self._disable('write_failed', f'{type(error).__name__}: {error}')
                return False
            self.recorded += 1
            self.bytes_written += size
            self.last_written_monotonic = now
            # No backlog or catch-up iterations: the next slot is relative to
            # this actual accepted offer, not an accumulated ideal schedule.
            self.next_write = now+1/self.hz
            return True

    def snapshot(self) -> dict:
        with self.lock:
            return {'kind': 'rolling_diagnostic', 'not_complete_evidence': True,
                    'complete_evidence': False, 'enabled': self.enabled, 'closed': self.closed,
                    'path': str(self.path), 'hz_wall': self.hz, 'part_max_bytes': self.max_bytes,
                    'backups': self.backups, 'max_retained_parts': self.backups+1,
                    'retained_upper_bound_bytes': (self.backups+1)*self.max_bytes,
                    'offered': self.offered, 'recorded': self.recorded,
                    'skipped_rate_limit': self.skipped_rate_limit,
                    'skipped_disabled': self.skipped_disabled, 'skipped_closed': self.skipped_closed,
                    'oversize_rejections': self.oversize_rejections,
                    'invalid_rejections': self.invalid_rejections,
                    'rotations': self.handler.rotations,
                    'overwritten_parts': self.handler.overwritten_parts,
                    'bytes_written': self.bytes_written,
                    'last_written_monotonic': self.last_written_monotonic,
                    'error_code': self.error_code, 'error': self.error, 'close_error': self.close_error}

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed, self.enabled = True, False
            self._close_handler()
