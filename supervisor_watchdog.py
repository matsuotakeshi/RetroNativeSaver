"""Progress monitoring for one worker lifetime; owns no process or mapping.

Create a fresh watchdog after each successful Job assignment. A captured hang
snapshot remains available after process exit for the existing failure policy.
"""
from ctypes import c_void_p, c_uint
from runtime_policy import PREPARATION_PHASES, watchdog_timeout, progress_key


def terminate_hung_worker(proc, kernel32, restart_exit_code):
    try:
        process_handle = getattr(
            proc,
            "_handle",
            None,
        )
        if process_handle:
            kernel32.TerminateProcess(
                c_void_p(int(process_handle)),
                c_uint(
                    restart_exit_code
                ),
            )
        else:
            proc.terminate()
    except Exception as exc:
        print(
            f"[watchdog] terminate warning: "
            f"{exc}",
            flush=True,
        )
        try:
            proc.kill()
        except Exception:
            pass


class WorkerWatchdog:
    def __init__(self, cfg, poll_seconds, read_trace, terminate):
        self.cfg = cfg
        self.poll_seconds = poll_seconds
        self.read_trace = read_trace
        self.terminate = terminate
        self.watchdog_key = None
        self.watchdog_since = None
        self.watchdog_last_check = 0.0
        self.watchdog_triggered = False
        self.watchdog_snapshot = None

    def check(self, proc, now_watchdog, runtime_trace_mm):
        if (
            runtime_trace_mm is not None
            and now_watchdog - self.watchdog_last_check
            >= self.poll_seconds
        ):
            self.watchdog_last_check = now_watchdog
            snapshot_now = self.read_trace(runtime_trace_mm)

            if snapshot_now:
                phase_now = str(
                    snapshot_now.get("phase", "")
                ).strip()

                phase_timeout = watchdog_timeout(phase_now, self.cfg)
                if phase_timeout is not None:
                    key_now = progress_key(snapshot_now, phase_now)

                    if key_now != self.watchdog_key:
                        self.watchdog_key = key_now
                        self.watchdog_since = now_watchdog
                    elif self.watchdog_since is not None:
                        timeout = phase_timeout
                        stuck_for = now_watchdog - self.watchdog_since

                        if stuck_for >= timeout:
                            self.watchdog_triggered = True
                            self.watchdog_snapshot = dict(snapshot_now)

                            print(
                                f"[watchdog] HANG detected "
                                f"pid={proc.pid} "
                                f"phase={phase_now} "
                                f"stuck={stuck_for:.1f}s "
                                f"cycle={snapshot_now.get('cycle', 0)} "
                                f"slot={snapshot_now.get('slot', 0)} "
                                f"[{snapshot_now.get('system', '')}] "
                                f"{snapshot_now.get('rom', '')}",
                                flush=True,
                            )
                            if phase_now in PREPARATION_PHASES or phase_now == "SLOT_SCHEDULER":
                                print("[watchdog] frontend stalled; closing session without ROM penalty or restart loop", flush=True)
                                return 1

                            print(
                                "[watchdog] terminating hung worker "
                                "with recycle exit code",
                                flush=True,
                            )

                            self.terminate(proc)

                            # Avoid repeated termination attempts while
                            # Windows completes process teardown.
                            self.watchdog_key = None
                            self.watchdog_since = None
                else:
                    self.watchdog_key = None
                    self.watchdog_since = None
