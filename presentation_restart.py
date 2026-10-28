"""Carry tile quarantine through an explicit presentation redraw.

The parent owns the temporary workspace. Read requests only after its worker
exits with RESELECT; a cleanup error never produces that success status.
Nothing here writes user settings, ROM lists, saves or states.
"""
import json
import os
from pathlib import Path

RESELECT = 77
FILENAME = 'presentation_restart.json'
MAX_BYTES = 1024 * 1024


def read_state(directory, expected_pid=None):
    path = Path(directory) / FILENAME
    if not path.exists() and expected_pid == 0:
        return set(), set(), {}
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Oversized presentation state')
    data = json.loads(raw)
    if not isinstance(data, dict) or type(data.get('pid')) is not int or data['pid'] != expected_pid:
        raise ValueError('Presentation state does not belong to this worker')
    banned, suspended, failures = data.get('banned'), data.get('suspended'), data.get('failures')
    if (not isinstance(banned, list) or any(not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(value, str) for value in pair) for pair in banned)
            or not isinstance(suspended, list) or any(not isinstance(s, str) for s in suspended)
            or not isinstance(failures, dict) or any(not isinstance(k, str) or type(v) is not int
                or v < 0 for k, v in failures.items())):
        raise ValueError('Invalid presentation safety state')
    return {tuple(pair) for pair in banned}, set(suspended), failures


def write_state(directory, banned, suspended, failures, *, pid):
    raw = json.dumps(dict(pid=pid, banned=sorted(banned), suspended=sorted(suspended),
                          failures=failures), ensure_ascii=False).encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('Oversized presentation state')
    path = Path(directory) / FILENAME
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(raw)
    os.replace(temporary, path)
