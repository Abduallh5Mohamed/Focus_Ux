"""Serialized private subprocess protocol; no HTTP service or credentials."""
import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import threading

from ..errors import ProcessingError

class ResidentSeparation:
    def __init__(self, python, script, home, model, timeout_s):
        self.command = [python, '-B', str(script), '--home', str(home), '--model', model]
        self.timeout_s = timeout_s
        self.process = None
        self.lock = threading.Lock()
        self.last_report = None
        atexit.register(self.close)

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.responses = queue.Queue()
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', env=env)
        process, responses = self.process, self.responses
        def read():
            for line in process.stdout:
                if line.startswith('FOCUS_SEP_RESULT='):
                    try:
                        responses.put(json.loads(line[len('FOCUS_SEP_RESULT='):]))
                    except ValueError:
                        responses.put({'error': 'Invalid resident protocol response'})
            responses.put({'error': 'Resident separator exited before producing a result'})
        threading.Thread(target=read, daemon=True).start()

    def request(self, src, out):
        with self.lock:
            try:
                self._start()
                self.process.stdin.write(json.dumps({'src': str(src), 'out': str(out)}) + '\n')
                self.process.stdin.flush()
                report = self.responses.get(timeout=self.timeout_s)
                if report.get('error'):
                    raise ProcessingError('resident speech separation failed', retryable=True,
                                          detail=report['error'])
                stems = report.get('stems', [])
                expected = Path(out).resolve()
                if len(stems) != 2 or any(not Path(p).resolve().is_relative_to(expected) for p in stems):
                    raise ProcessingError('invalid separated output paths', retryable=False)
                self.last_report = report
                return stems
            except (OSError, queue.Empty, ProcessingError) as exc:
                self.close()
                if isinstance(exc, ProcessingError):
                    raise
                raise ProcessingError('resident separator unavailable or timed out', retryable=True,
                                      detail=type(exc).__name__) from exc

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            for handle in (process.stdin, process.stdout):
                if handle is not None:
                    handle.close()
