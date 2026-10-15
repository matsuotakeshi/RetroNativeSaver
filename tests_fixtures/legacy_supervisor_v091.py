# Historical comparison fixture; isolated operations only. Do not use at runtime.
def classify(snapshot, unsigned_code, watchdog_triggered, native_crash_codes):
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

def record_runtime_failure(snapshot, watchdog_triggered):
    crash_system = str(snapshot.get('system', '')).strip()
    crash_rom = str(snapshot.get('rom', '')).strip()
    crash_phase = str(snapshot.get('phase', '')).strip()
    failure_kind = 'hang' if watchdog_triggered else 'crash'
    if crash_system:
        new_count = session_crash_counts.get(crash_system, 0) + 1
        session_crash_counts[crash_system] = new_count
        print(f'[session-safety] {failure_kind} [{crash_system}] count={new_count}/{session_system_crash_limit} phase={crash_phase}', flush=True)
        if session_rom_quarantine_enabled and crash_rom:
            bucket = session_quarantine.setdefault(crash_system, set())
            if crash_rom not in bucket:
                bucket.add(crash_rom)
                print(f'[session-safety] ROM quarantined [{crash_system}] {crash_rom}', flush=True)
        rom_is_whitelisted = persistent_rom_whitelist_enabled and crash_rom and _rom_in_name_map(persistent_whitelisted, crash_system, crash_rom)
        if rom_is_whitelisted:
            print(f'[persistent-safety] WHITELIST protects [{crash_system}] {crash_rom}; persistent failure evidence unchanged (session quarantine still applies)', flush=True)
        elif persistent_rom_blacklist_enabled and crash_rom:
            persistent_failures, newly_blacklisted, already_recorded = _record_persistent_rom_failure(persistent_rom_state, persistent_rom_blacklist_path, persistent_session_id, persistent_rom_blacklist_threshold_sessions, crash_system, crash_rom, crash_phase, failure_kind)
            if already_recorded:
                print(f'[persistent-safety] evidence already recorded this session [{crash_system}] {crash_rom} sessions={persistent_failures}/{persistent_rom_blacklist_threshold_sessions}', flush=True)
            elif newly_blacklisted:
                print(f'[persistent-safety] ROM BLACKLISTED [{crash_system}] {crash_rom} after {persistent_failures} separate screen-saver sessions', flush=True)
            else:
                print(f'[persistent-safety] failure evidence [{crash_system}] {crash_rom} sessions={persistent_failures}/{persistent_rom_blacklist_threshold_sessions}; ROM will be retried next screen-saver session', flush=True)
        if new_count >= session_system_crash_limit and crash_system not in session_disabled_systems:
            session_disabled_systems.add(crash_system)
            print(f'[session-safety] SYSTEM SUSPENDED [{crash_system}] after {new_count} runtime/startup crash/hang event(s); it will return next time the screen saver starts', flush=True)
