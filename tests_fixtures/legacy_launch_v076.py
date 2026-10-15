"""v0.20.76 CLI and main blocks, test only."""
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
    args = ap.parse_args(cli_args)
    return args


def parse_rom_list_args(cli_args, APP_DIR):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom-lists", action="store_true")
    parser.add_argument("--config", default=str(APP_DIR / "config.json"))
    options = parser.parse_args(cli_args)
    return options


def display_mode(launch_mode, cfg, args):
    preview_mode = launch_mode == "preview"
    if launch_mode == "screen":
        fullscreen = True
    elif preview_mode:
        fullscreen = False
    else:
        fullscreen = bool(cfg.get("fullscreen", True) and not args.windowed)
    return preview_mode, fullscreen


def requested_slot_count(cfg, args, preview_mode):
    requested_slots = (
        max(1, int(args.slots))
        if args.slots is not None
        else (
            int(cfg.get("preview_slot_count", 1))
            if preview_mode
            else int(cfg.get("windowed_slot_count", 4))
        )
    )
    return requested_slots


def cycle_settings(cfg, args, preview_mode):
    cycle_enabled = (
        bool(cfg.get("preview_cycle_enabled", False))
        if preview_mode
        else bool(cfg.get("cycle_enabled", True))
    )
    cycle_seconds = max(
        1.0,
        float(
            args.cycle_seconds
            if args.cycle_seconds is not None
            else (
                cfg.get("preview_cycle_seconds", 30)
                if preview_mode
                else cfg.get("cycle_seconds", 240)
            )
        ),
    )
    retry_attempts = int(cfg.get("startup_retry_attempts", 5))
    overlay_cfg = cfg.get("overlay", {})
    if not isinstance(overlay_cfg, dict):
        overlay_cfg = {}

    fade_enabled = bool(cfg.get("fade_enabled", True))
    fade_duration_ms = max(0, int(cfg.get("fade_duration_ms", 800)))
    fade_duration = fade_duration_ms / 1000.0

    runtime_heartbeat_seconds = max(
        1.0,
        float(cfg.get("runtime_heartbeat_seconds", 10.0)),
    )
    return cycle_enabled, cycle_seconds, retry_attempts, overlay_cfg, fade_enabled, fade_duration, runtime_heartbeat_seconds


def filter_preview_systems(systems):
    before = len(systems)
    systems = [
        s for s in systems
        if not bool(s.get("process_recycle_required", False))
    ]
    skipped = before - len(systems)
    if skipped:
        print(
            f"[preview] skipped {skipped} process-isolated system(s)",
            flush=True,
        )
    return systems


def apply_session_suspensions(systems, session_quarantine, session_disabled_systems):
    for system in systems:
        system_name = str(
            system.get("name", system.get("id", "?"))
        )
        if system_name in session_disabled_systems:
            system["enabled"] = False
            print(
                f"[session-safety] SUSPENDED [{system_name}] "
                "for remainder of this screen-saver session",
                flush=True,
            )

    quarantine_total = sum(
        len(names)
        for names in session_quarantine.values()
    )
    if quarantine_total or session_disabled_systems:
        print(
            f"[session-safety] worker state: "
            f"quarantined_roms={quarantine_total} "
            f"suspended_systems={len(session_disabled_systems)}",
            flush=True,
        )
    return None
