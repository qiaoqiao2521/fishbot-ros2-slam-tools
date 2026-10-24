#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""One offline search, one existing line-oriented MINCO process."""
import json
import os
import select
import subprocess
import tempfile
import time
import warnings


class NativeSession:
    """Sequential unbuffered requests; never more than one pending reply."""
    def __init__(self, executable, timeout=10):
        self.timeout=timeout;self.closed=False;self.diagnostic="";self.failed_exchange=False
        self.stderr=tempfile.TemporaryFile()
        try:
            self.process=subprocess.Popen([str(executable)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=self.stderr,bufsize=0)
        except OSError as error:
            self.stderr.close();self.closed=True
            raise ValueError(f"native session unavailable: {error}") from error
        os.set_blocking(self.process.stdin.fileno(),False)
        os.set_blocking(self.process.stdout.fileno(),False)

    def __enter__(self):
        return self

    def __exit__(self,kind,*_):
        self.close(check_exit=kind is None)

    def close(self,check_exit=True):
        if self.closed:
            return
        self.closed=True
        self.process.stdin.close()
        try:
            self.process.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            try:self.process.wait(timeout=1.)
            except subprocess.TimeoutExpired:
                warnings.warn(f"native PID {self.process.pid} termination unconfirmed",RuntimeWarning)
        self.process.stdout.close()
        end=self.stderr.seek(0,os.SEEK_END);self.stderr.seek(max(0,end-4096))
        self.diagnostic=self.stderr.read().decode("utf-8",errors="replace").strip()
        self.stderr.close()
        if check_exit and not self.failed_exchange and self.process.returncode!=0:
            raise ValueError(f"native process exit={self.process.returncode}"+
                (": "+self.diagnostic if self.diagnostic else ""))

    def failed(self,reason):
        self.failed_exchange=True
        self.close(check_exit=False)
        return ValueError(reason+(": "+self.diagnostic if self.diagnostic else ""))

    def exchange(self,request):
        if self.closed:
            raise ValueError("native session already closed")
        # Serialization errors have not sent a request and do not desynchronize
        # the stream. Native error objects also consume exactly one reply.
        payload=(json.dumps(request,allow_nan=False)+"\n").encode("utf-8")
        deadline=time.monotonic()+self.timeout
        sent=0;reply=bytearray()
        try:
            while sent<len(payload):
                remaining=deadline-time.monotonic()
                if remaining<=0 or not select.select([], [self.process.stdin], [], remaining)[1]:
                    raise self.failed("native request timeout")
                try:sent+=os.write(self.process.stdin.fileno(),payload[sent:])
                except BlockingIOError:continue
            while b"\n" not in reply:
                remaining=deadline-time.monotonic()
                if remaining<=0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                    raise self.failed("native reply timeout")
                try:chunk=os.read(self.process.stdout.fileno(),65536)
                except BlockingIOError:continue
                if not chunk:
                    raise self.failed("native reply EOF")
                reply.extend(chunk)
            line,extra=bytes(reply).split(b"\n",1)
            if extra or not line.startswith(b"MincoResult "):
                raise self.failed("unexpected native reply framing")
            result=json.loads(line[len(b"MincoResult "):])
            if not isinstance(result,dict):
                raise ValueError("native reply is not an object")
            return result
        except (OSError,UnicodeError,ValueError) as error:
            if self.closed:
                raise
            raise self.failed(f"native exchange failed: {error}") from error
