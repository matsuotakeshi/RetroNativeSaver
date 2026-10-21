"""Opt-in application logs, selected before any workers or native cores start."""
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile

ENV_KEY = 'RNS_LOG_OUTPUT'
CHILD_FLAGS = ('--worker', '--slot-worker', '--supervisor-guard')


def config_path(argv, app_dir):
    path = str(Path(app_dir) / 'config.json')
    for index, arg in enumerate(argv):
        if arg == '--config' and index + 1 < len(argv):
            path = argv[index + 1]
        elif arg.startswith('--config='):
            path = arg.split('=', 1)[1]
    return Path(path)


def enabled(argv, app_dir, environment):
    # Children inherit the parent's choice, even if the config changes mid-session.
    if any(flag in argv for flag in CHILD_FLAGS) and ENV_KEY in environment:
        return environment[ENV_KEY] == '1'
    try:
        data = json.loads(config_path(argv, app_dir).read_text(encoding='utf-8'))
        return isinstance(data, dict) and data.get('log_output_enabled') is True
    except (OSError, ValueError):
        # The normal config loader/UI still reports errors. Never create logs by default.
        return False


class QuietStream:
    encoding = 'utf-8'

    def write(self, value):
        return len(value) if value is not None else 0

    def flush(self):
        pass

    def isatty(self):
        return False


def open_log(app_dir):
    for directory in (Path(app_dir) / 'logs', Path(tempfile.gettempdir()) / 'retro_native_saver_logs'):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f'retro_native_saver_{datetime.datetime.now():%Y%m%d}.log'
            return directory, path, path.open('a', encoding='utf-8', buffering=1)
        except OSError:
            continue
    return Path(app_dir) / 'logs', None, None


def install(app_dir, argv):
    from diagnostic_io import _DiagnosticStream
    active = enabled(argv, app_dir, os.environ)
    os.environ[ENV_KEY] = '1' if active else '0'
    directory, path, handle = open_log(app_dir) if active else (Path(app_dir) / 'logs', None, None)
    if active:
        sys.stdout = _DiagnosticStream(sys.stdout, handle, 'OUT')
        sys.stderr = _DiagnosticStream(sys.stderr, handle, 'ERR')
    else:
        sys.stdout, sys.stderr = QuietStream(), QuietStream()
    # Existing explicit measurement launchers remain an opt-in diagnostic tool.
    if os.environ.get('RNS_STARTUP_TIMING') == '1':
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return directory, path, handle
