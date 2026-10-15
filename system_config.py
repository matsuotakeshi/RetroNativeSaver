"""System JSON loading and CLI overrides, preserving legacy behavior."""
import json
from pathlib import Path


def read_system_config(path):
    """Worker-time file boundary; retain legacy JSON errors and source identity.

    Parent config snapshots do not freeze these files. Invalid machine files
    are logged/skipped by the caller, while favorites remain independently live.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_config_path"] = str(path)
    return data

def load_system_configs(systems_dir: Path):
    systems = []
    if not systems_dir.exists():
        raise RuntimeError(f"systems directory not found: {systems_dir}")

    for path in sorted(systems_dir.glob("*.json")):
        try:
            systems.append(read_system_config(path))
        except Exception as exc:
            print(f"[config] ERROR {path.name}: {exc}")

    return systems


def apply_cli_system_overrides(systems, args):
    if args.system:
        wanted = args.system.strip().lower()
        systems = [
            s for s in systems
            if str(s.get("id", "")).lower() == wanted
            or str(s.get("name", "")).lower() == wanted
        ]
        if not systems:
            raise RuntimeError(f"System not found: {args.system}")
        if args.force_system:
            for s in systems:
                s["enabled"] = True

    if args.no_hw_readback:
        for s in systems:
            s["hw_readback"] = False

    if args.env_trace_frames > 0:
        for s in systems:
            s["env_trace_frames"] = args.env_trace_frames

    if args.disable_log_interface:
        for s in systems:
            s["provide_log_interface"] = False

    if args.disable_perf_interface:
        for s in systems:
            s["provide_perf_interface"] = False

    if args.no_frame_rebind:
        for s in systems:
            s["frame_rebind_context"] = False

    if args.trace_core_vars:
        for s in systems:
            s["trace_core_vars"] = True

    return systems


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
    from runtime_policy import DEFAULT_CYCLE_SECONDS
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
                else cfg.get("cycle_seconds", DEFAULT_CYCLE_SECONDS)
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
