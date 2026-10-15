# Historical comparison fixture; isolated operations only. Do not use at runtime.
def supervisor_main():
    if runtime_trace_mm is not None and now_watchdog - watchdog_last_check >= worker_watchdog_poll_seconds:
        watchdog_last_check = now_watchdog
        snapshot_now = read_runtime_trace(runtime_trace_mm)
        if snapshot_now:
            phase_now = str(snapshot_now.get('phase', '')).strip()
            phase_timeout = watchdog_timeout(phase_now, supervisor_cfg)
            if phase_timeout is not None:
                key_now = progress_key(snapshot_now, phase_now)
                if key_now != watchdog_key:
                    watchdog_key = key_now
                    watchdog_since = now_watchdog
                elif watchdog_since is not None:
                    timeout = phase_timeout
                    stuck_for = now_watchdog - watchdog_since
                    if stuck_for >= timeout:
                        watchdog_triggered = True
                        watchdog_snapshot = dict(snapshot_now)
                        print(f"[watchdog] HANG detected pid={proc.pid} phase={phase_now} stuck={stuck_for:.1f}s cycle={snapshot_now.get('cycle', 0)} slot={snapshot_now.get('slot', 0)} [{snapshot_now.get('system', '')}] {snapshot_now.get('rom', '')}", flush=True)
                        if phase_now in PREPARATION_PHASES or phase_now == 'SLOT_SCHEDULER':
                            print('[watchdog] frontend stalled; closing session without ROM penalty or restart loop', flush=True)
                            return 1
                        print('[watchdog] terminating hung worker with recycle exit code', flush=True)
                        try:
                            process_handle = getattr(proc, '_handle', None)
                            if process_handle:
                                kernel32.TerminateProcess(c_void_p(int(process_handle)), c_uint(WORKER_RESTART_EXIT_CODE))
                            else:
                                proc.terminate()
                        except Exception as exc:
                            print(f'[watchdog] terminate warning: {exc}', flush=True)
                            try:
                                proc.kill()
                            except Exception:
                                pass
                        watchdog_key = None
                        watchdog_since = None
            else:
                watchdog_key = None
                watchdog_since = None
