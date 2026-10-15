"""Pure policies shared by the supervisor and independent tile workers."""
import math

DEFAULT_CYCLE_SECONDS = 240
DEFAULT_RUN_HANG_TIMEOUT = 15
DEFAULT_START_HANG_TIMEOUT = 45

PREPARATION_PHASES = frozenset({'WORKER_STARTING', 'CONFIG_LOAD', 'TITLE_CATALOG', 'ROM_CATALOG'})
NATIVE_CRASH_CODES = frozenset({0xC0000005, 0xC000001D, 0xC0000409, 0xC0000374})


def persistent_failure(snapshot, exit_code):
    """Only native faults during emulation are durable ROM evidence.

    Startup, Python exceptions and timeouts remain session-only: none proves
    that a ROM is defective. Whitelisting is applied by the caller as before.
    """
    return (exit_code is not None and (exit_code & 0xffffffff) in NATIVE_CRASH_CODES
            and (snapshot or {}).get('phase') in {'RUN_ENTER', 'SLOT_RUNNING', 'WAIT_FRAME'})


def watchdog_timeout(phase, cfg):
    if phase in PREPARATION_PHASES:
        return max(1., float(cfg.get('worker_prepare_hang_timeout_seconds', 120)))
    if phase == 'START_ENTER':
        return max(1., float(cfg.get('worker_start_hang_timeout_seconds', DEFAULT_START_HANG_TIMEOUT)))
    if phase in {'RUN_ENTER', 'SLOT_SCHEDULER'}:
        return max(1., float(cfg.get('worker_run_hang_timeout_seconds', DEFAULT_RUN_HANG_TIMEOUT)))
    return None


class FramePacer:
    """Emulate at core rate, present at a separate rate, never build a backlog."""
    def __init__(self, core_fps, display_fps, now):
        core_fps, display_fps = float(core_fps), float(display_fps)
        if not all(math.isfinite(x) and x > 0 for x in (core_fps, display_fps)):
            raise ValueError('Frame rates must be finite and positive')
        self.run_period = 1 / core_fps
        self.display_period = 1 / min(core_fps, display_fps)
        self.next_run = self.next_display = now

    def should_present(self, now):
        if now + 1e-9 < self.next_display:
            return False
        self.next_display += self.display_period
        if self.next_display <= now:
            self.next_display = now + self.display_period
        return True

    def delay(self, now):
        self.next_run += self.run_period
        if self.next_run < now - self.run_period:
            self.next_run = now
        return max(0., self.next_run - now)


def progress_key(snapshot_now, phase_now):
    """Supervisor progress identity; timestamp/raw changes alone are ignored."""
    key_now = (
        phase_now,
        int(snapshot_now.get("cycle", 0)),
        int(snapshot_now.get("slot", 0)),
        str(snapshot_now.get("system", "")),
        str(snapshot_now.get("rom", "")),
        int(snapshot_now.get("loop_count", 0)),
        int(snapshot_now.get("call_count", 0)),
    )
    return key_now

def tile_hung(record, cfg, now):
    """Tile policy: absolute startup age, then last progress age. Defaults stay 45/15."""
    timeout = max(1., float(cfg.get('worker_run_hang_timeout_seconds', DEFAULT_RUN_HANG_TIMEOUT)))
    startup_timeout = max(1., float(cfg.get('worker_start_hang_timeout_seconds', DEFAULT_START_HANG_TIMEOUT)))
    hung = ((not record['ready'] and now - record['spawned'] >= startup_timeout)
            or (record['ready'] and now - record['progress'] >= timeout))
    return hung

def tile_exit_status(code, phase, complete_code):
    """Called after poll reports exit; classify without taking process actions."""
    if code == 0 and phase == 'SLOT_USER_EXIT':
        return "user_exit"
    if code != complete_code or phase != 'SLOT_COMPLETE':
        return "failure"
    return "complete"


def _is_session_runtime_crash(snapshot, unsigned_code, native_crash_codes):
    """
    Decide whether one worker death should count against a ROM/system.

    RUN_ENTER:
        Counts only for a raw native process crash. This means the core died
        before returning from run_frame().

    RUN_EXCEPTION:
        Counts because the worker already identified a run_frame failure.

    START_ENTER:
        Counts only for a raw native process crash during core init/load.

    START_NATIVE_FAULT:
        Counts because the caught startup exception was a native AV.

    Shutdown phases are deliberately excluded. A PSP/Flycast/Dolphin teardown
    bug should recycle the worker, not punish the ROM that happened to be
    running.
    """
    if not snapshot:
        return False

    phase = str(snapshot.get("phase", ""))
    is_raw_native_crash = unsigned_code in native_crash_codes

    if phase == "RUN_EXCEPTION":
        return True
    if phase == "RUN_ENTER" and is_raw_native_crash:
        return True
    if phase == "START_NATIVE_FAULT":
        return True
    if phase == "START_ENTER" and is_raw_native_crash:
        return True

    return False


def cycle_frame_timing(av_infos):
    fps_values = []
    for av in av_infos:
        fps = float(av.timing.fps)
        if 1 < fps <= 240:
            fps_values.append(fps)
    fps = max(fps_values) if fps_values else 60.0

    step = 1.0 / fps
    return fps, step


def cycle_fade_alpha(elapsed, fade_enabled, fade_duration, cycle_enabled, cycle_seconds):
    fade_alpha = 0

    if fade_enabled and fade_duration > 0:
        if elapsed < fade_duration:
            fade_alpha = max(
                fade_alpha,
                int(round(
                    255.0 * (1.0 - elapsed / fade_duration)
                )),
            )

        if cycle_enabled:
            remaining = cycle_seconds - elapsed
            if remaining < fade_duration:
                fade_alpha = max(
                    fade_alpha,
                    int(round(
                        255.0 * (
                            1.0 - max(0.0, remaining) / fade_duration
                        )
                    )),
                )
    return fade_alpha


def worker_runtime_failure(snapshot, unsigned_code, watchdog_triggered, native_crash_codes):
    """Supervisor policy; retain its distinction from independent tile failures."""
    runtime_failure = _is_session_runtime_crash(
        snapshot,
        unsigned_code,
        native_crash_codes,
    )
    if watchdog_triggered and snapshot:
        runtime_failure = (
            str(snapshot.get("phase", ""))
            in {"RUN_ENTER", "START_ENTER"}
        )

    return runtime_failure
