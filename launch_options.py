"""Command-line parsing, preserving Windows screensaver switch handling."""
import argparse


def parse_screensaver_args(argv):
    """
    Windows screen saver command line:
      /s              run full-screen saver
      /c or /c:HWND   configuration
      /p HWND          preview inside Display Settings preview window
    """
    mode = "normal"
    parent_hwnd = None
    remaining = []

    i = 0
    while i < len(argv):
        arg = str(argv[i])
        low = arg.lower()

        if low in ("/s", "-s"):
            mode = "screen"
            i += 1
            continue

        if low == "/c" or low == "-c" or low.startswith("/c:") or low.startswith("-c:"):
            mode = "config"
            i += 1
            continue

        if low in ("/p", "-p"):
            mode = "preview"
            if i + 1 < len(argv):
                try:
                    parent_hwnd = int(str(argv[i + 1]), 0)
                except ValueError:
                    parent_hwnd = None
                i += 2
            else:
                i += 1
            continue

        if low.startswith("/p:") or low.startswith("-p:"):
            mode = "preview"
            try:
                parent_hwnd = int(arg.split(":", 1)[1], 0)
            except ValueError:
                parent_hwnd = None
            i += 1
            continue

        remaining.append(arg)
        i += 1

    return mode, parent_hwnd, remaining


def parse_main_args(cli_args, APP_DIR):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(APP_DIR / "config.json"))
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--favorites", action="store_true")
    ap.add_argument("--system", default=None)
    ap.add_argument("--force-system", action="store_true")
    ap.add_argument("--no-hw-readback", action="store_true")
    ap.add_argument("--env-trace-frames", type=int, default=0)
    ap.add_argument("--disable-log-interface", action="store_true")
    ap.add_argument("--disable-perf-interface", action="store_true")
    ap.add_argument("--no-frame-rebind", action="store_true")
    ap.add_argument("--trace-core-vars", action="store_true")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--cycle-seconds", type=float, default=None)
    ap.add_argument("--slots", type=int, default=None)
    ap.add_argument("--presentation", choices=('auto', 'normal', 'single-system'), default='auto')
    args = ap.parse_args(cli_args)
    return args


def parse_rom_list_args(cli_args, APP_DIR):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom-lists", action="store_true")
    parser.add_argument("--config", default=str(APP_DIR / "config.json"))
    options = parser.parse_args(cli_args)
    return options


def load_config(path):
    """Parent and worker both reject missing, malformed and non-object configs."""
    import json
    from pathlib import Path
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return value


def load_supervisor_config(remaining, app_dir):
    """Fail before creating a backdrop or launching workers on config errors."""
    config_path = parse_main_args(remaining, app_dir).config
    try:
        return load_config(config_path)
    except Exception as exc:
        print(f"[supervisor] configuration error; saver not started: {config_path}: {exc}", flush=True)
        raise
