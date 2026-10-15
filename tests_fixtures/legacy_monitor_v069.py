"""v0.20.69 expressions extracted verbatim; test only."""

def progress_key(snapshot_now, phase_now):
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
    timeout = max(1., float(cfg.get('worker_run_hang_timeout_seconds', 15)))
    startup_timeout = max(1., float(cfg.get('worker_start_hang_timeout_seconds', 45)))
    hung = ((not record['ready'] and now - record['spawned'] >= startup_timeout)
            or (record['ready'] and now - record['progress'] >= timeout))
    return hung

def tile_exit_status(code, phase, COMPLETE):
    if code == 0 and phase == 'SLOT_USER_EXIT':
        return "user_exit"
    if code != COMPLETE or phase != 'SLOT_COMPLETE':
        return "failure"
    return "complete"
