"""Small optional receipts for the existing owned arm query, not another owner.

The original task deadline and result admission remain in cooperation_arm.
Missing/unwritable diagnostics warn and cannot stop an otherwise valid query.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time


class QueryTrace:
    def __init__(self, directory, query_id, started_monotonic_s):
        self.directory = Path(directory)
        self.query_id = query_id
        self.started = started_monotonic_s

    def context(self):
        return {'directory': str(self.directory), 'query_id': self.query_id,
                'started_monotonic_s': self.started}

    def emit(self, stage, **fields):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            row = {'query_id': self.query_id, 'stage': stage, 'pid': os.getpid(),
                   'wall_s': time.time(), 'elapsed_wall_s': time.monotonic()-self.started,
                   **fields}
            encoded = (json.dumps(row, allow_nan=False, separators=(',', ':'))+'\n').encode()
            fd = os.open(self.directory/'stages.jsonl', os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
            try:
                os.write(fd, encoded)
            finally:
                os.close(fd)
        except (OSError, TypeError, ValueError) as error:
            logging.warning('Could not record arm query stage %s: %s', stage, error)

    def save(self, name, value):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
        except (OSError, TypeError, ValueError) as error:
            logging.warning('Could not record arm query receipt %s: %s', name, error)


def optional_query_trace(manifest, query_id, started):
    config = manifest.get('pretrained_grasp', {})
    directory = manifest.get('arm_query_evidence_directory')
    if not directory and isinstance(config, dict):
        directory = config.get('output_directory') if config.get('enabled') else None
    if not isinstance(directory, str) or not directory:
        return None
    return QueryTrace(Path(directory)/'query-receipts'/query_id, query_id, started)


def trace_from_context(context):
    if not isinstance(context, dict) or not context.get('directory'):
        return None
    return QueryTrace(context['directory'], context.get('query_id', 'unknown'),
                      context.get('started_monotonic_s', time.monotonic()))


def emit(trace, stage, **fields):
    if trace is not None:
        trace.emit(stage, **fields)
