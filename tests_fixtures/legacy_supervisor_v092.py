# Historical comparison fixture; isolated operations only. Do not use at runtime.
def load_safety_state():
    persistent_rom_state = _empty_persistent_rom_state()
    persistent_blacklisted = {}
    if persistent_rom_blacklist_enabled:
        persistent_rom_state = _load_persistent_rom_state(persistent_rom_blacklist_path)
        persistent_blacklisted = _persistent_blacklisted_roms(persistent_rom_state)
    persistent_rom_whitelist_state = _empty_persistent_rom_whitelist()
    persistent_whitelisted = {}
    if persistent_rom_whitelist_enabled:
        persistent_rom_whitelist_state = _load_persistent_rom_whitelist(persistent_rom_whitelist_path, persistent_rom_whitelist_seed_path)
        persistent_whitelisted = _persistent_whitelisted_roms(persistent_rom_whitelist_state)
    effective_persistent_blacklisted, whitelist_rescued = _apply_persistent_whitelist(persistent_blacklisted, persistent_whitelisted)
    session_quarantine = {system_name: set(rom_names) for system_name, rom_names in effective_persistent_blacklisted.items()}
    session_crash_counts = {}
    session_disabled_systems = set()
    persistent_blacklist_total = sum((len(names) for names in persistent_blacklisted.values()))
    effective_blacklist_total = sum((len(names) for names in effective_persistent_blacklisted.values()))
    persistent_whitelist_total = sum((len(names) for names in persistent_whitelisted.values()))
    print(f"[persistent-safety] policy: enabled={('yes' if persistent_rom_blacklist_enabled else 'no')} threshold={persistent_rom_blacklist_threshold_sessions} session_id={persistent_session_id} file={persistent_rom_blacklist_path}", flush=True)
    print(f"[persistent-safety] whitelist policy: enabled={('yes' if persistent_rom_whitelist_enabled else 'no')} file={persistent_rom_whitelist_path}", flush=True)
    print(f'[persistent-safety] loaded {persistent_blacklist_total} blacklisted ROM(s), {persistent_whitelist_total} whitelisted ROM(s), rescued={whitelist_rescued}, effective_blacklist={effective_blacklist_total}', flush=True)
    print(f"[session-safety] supervisor policy: rom_quarantine={('on' if session_rom_quarantine_enabled else 'off')} system_crash_limit={session_system_crash_limit}", flush=True)
    print(f'[watchdog] supervisor policy: run_hang_timeout={worker_run_hang_timeout_seconds:.1f}s start_hang_timeout={worker_start_hang_timeout_seconds:.1f}s poll={worker_watchdog_poll_seconds:.2f}s', flush=True)
    return (persistent_rom_state, persistent_whitelisted, session_quarantine, session_crash_counts, session_disabled_systems)

def prepare_worker_launch():
    if getattr(sys, 'frozen', False):
        cmd = [sys.executable, '--worker', *raw_args]
    else:
        cmd = [sys.executable, '-u', str(Path(__file__).resolve()), '--worker', *raw_args]
    print(f'[supervisor] starting worker parent_pid={os.getpid()} cmd={cmd}', flush=True)
    child_env = os.environ.copy()
    child_env['RNS_SLOT_SESSION_ID'] = persistent_session_id
    if runtime_trace_tag:
        child_env[RUNTIME_TRACE_ENV] = runtime_trace_tag
    quarantine_payload = {system_name: sorted(rom_names) for system_name, rom_names in session_quarantine.items() if rom_names}
    child_env[SESSION_QUARANTINE_ENV] = json.dumps(quarantine_payload, ensure_ascii=False)
    child_env[SESSION_DISABLED_SYSTEMS_ENV] = json.dumps(sorted(session_disabled_systems), ensure_ascii=False)
    quarantine_total = sum((len(names) for names in session_quarantine.values()))
    if quarantine_total or session_disabled_systems:
        print(f'[session-safety] passing state to worker: quarantined_roms={quarantine_total} suspended_systems={len(session_disabled_systems)}', flush=True)
    return (cmd, child_env)
