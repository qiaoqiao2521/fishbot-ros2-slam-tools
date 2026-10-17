"""Bounded independent evidence recording without altering ROS messages or files.

The caller creates an exclusive UTF-8 stream and owns collection shutdown and
score admission. This helper neither rotates nor deletes evidence. Completeness
is only true after a successful close and no rejected or uncertain records.
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import TextIO

DEFAULT_MAX_BYTES = 1024 ** 3
MAX_BYTES = 4 * 1024 ** 3
MAX_MANIFESTS = 16


class EvidenceRecorder:
    """Record complete JSONL lines and latch the first failure for the caller."""

    def __init__(self, stream: TextIO, max_bytes: int = DEFAULT_MAX_BYTES):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise ValueError('max_bytes must be an integer')
        if not 1024 <= max_bytes <= MAX_BYTES:
            raise ValueError('max_bytes must be between 1024 bytes and 4 GiB')
        if not all(callable(getattr(stream, name, None)) for name in ('write', 'flush', 'close')):
            raise ValueError('stream must be a writable UTF-8 text stream')
        encoding = getattr(stream, 'encoding', None)
        if encoding is not None and encoding.lower().replace('-', '').replace('_', '') != 'utf8':
            raise ValueError('stream must use UTF-8 encoding')
        if getattr(stream, 'closed', False):
            raise ValueError('stream must be open')
        self._stream = stream
        self._max_bytes = max_bytes
        self._lock = threading.RLock()
        self._manifests: set[str] = set()
        self._offered = self._written = self._bytes = self._deduplicated = 0
        self._failed = self._truncated = self._closed = self._bytes_uncertain = False
        self._error: str | None = None
        self._error_code: str | None = None
        self._errors: list[dict[str, str]] = []

    def _fail(self, code: str, detail: str) -> None:
        self._failed = self._truncated = True
        # Preserve the first cause; close failures must never erase it.
        if self._error is None:
            self._error_code, self._error = code, detail
        self._errors.append({'code': code, 'error': detail})

    @staticmethod
    def _position(stream: TextIO) -> int | None:
        try:
            position = stream.tell()
        except Exception:
            return None
        return position if isinstance(position, int) and not isinstance(position, bool) and position >= 0 else None

    @staticmethod
    def _encode(value: dict) -> tuple[dict, str | None]:
        if not isinstance(value, dict):
            raise ValueError('evidence must be a dictionary')
        output = value
        digest = None
        if value.get('topic') == 'physics':
            payload = value.get('payload')
            if not isinstance(payload, dict) or not isinstance(payload.get('source'), dict):
                raise ValueError('physics evidence requires payload.source')
            source = payload['source']
            if not isinstance(source.get('manifest'), dict):
                raise ValueError('physics evidence requires an actual manifest object')
            canonical = json.dumps(source['manifest'], sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False).encode('utf-8')
            digest = hashlib.sha256(canonical).hexdigest()
            if 'manifest_ref_sha256' in value and value['manifest_ref_sha256'] != digest:
                raise ValueError('manifest_ref_sha256 conflicts with the actual manifest')
            # Copy only the containers we edit. Serialization retains no input references.
            output = {**value, 'payload': {**payload, 'source': dict(source)},
                      'manifest_ref_sha256': digest}
        return output, digest

    def record(self, value: dict) -> bool:
        """Return False on failure, retaining all earlier valid lines unchanged."""
        with self._lock:
            self._offered += 1
            if self._failed:
                return False
            if self._closed:
                self._fail('closed', 'evidence was offered after close')
                return False
            try:
                output, digest = self._encode(value)
                duplicate = digest is not None and digest in self._manifests
                if digest is not None and not duplicate and len(self._manifests) >= MAX_MANIFESTS:
                    self._fail('manifest_limit', 'more than 16 distinct actual manifests were offered')
                    return False
                if duplicate:
                    del output['payload']['source']['manifest']
                text = json.dumps(output, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'
                encoded_size = len(text.encode('utf-8'))
            except Exception as error:
                self._fail('invalid_json', f'evidence serialization failed: {type(error).__name__}')
                return False
            if self._bytes + encoded_size > self._max_bytes:
                self._fail('byte_budget', 'the next complete UTF-8 evidence line exceeds max_bytes')
                return False
            before = self._position(self._stream)
            try:
                count = self._stream.write(text)
            except Exception as error:
                after = self._position(self._stream)
                if before is not None and after is not None and 0 <= after - before <= encoded_size:
                    self._bytes += after - before
                else:
                    self._bytes_uncertain = True
                self._fail('write_failed', f'evidence write failed: {type(error).__name__}')
                return False
            if not isinstance(count, int) or isinstance(count, bool) or count != len(text):
                if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= len(text):
                    self._bytes += len(text[:count].encode('utf-8'))
                else:
                    self._bytes_uncertain = True
                self._fail('partial_write', 'the stream did not confirm one complete evidence line')
                return False
            self._bytes += encoded_size
            try:
                self._stream.flush()
            except Exception as error:
                self._fail('flush_failed', f'evidence flush failed: {type(error).__name__}')
                return False
            self._written += 1
            if digest is not None:
                self._manifests.add(digest)
            if duplicate:
                self._deduplicated += 1
            return True

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'schema': 1, 'max_bytes': self._max_bytes,
                'offered': self._offered, 'written': self._written, 'bytes': self._bytes,
                'deduplicated': self._deduplicated, 'incomplete': self._offered - self._written,
                'manifest_sources': len(self._manifests), 'manifest_source_limit': MAX_MANIFESTS,
                'failed': self._failed, 'error': self._error, 'error_code': self._error_code,
                'errors': [entry.copy() for entry in self._errors],
                'truncated': self._truncated, 'bytes_uncertain': self._bytes_uncertain,
                'closed': self._closed,
                'capture_complete': self._closed and not self._failed and self._offered == self._written,
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._stream.flush()
            except Exception as error:
                self._fail('close_flush_failed', f'evidence close flush failed: {type(error).__name__}')
            try:
                self._stream.close()
            except Exception as error:
                self._fail('close_failed', f'evidence close failed: {type(error).__name__}')
            self._closed = True
