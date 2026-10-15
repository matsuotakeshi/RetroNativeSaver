"""Unmodified v0.20.70 functions, for tests only."""
import datetime

def _persistent_entry_for_rom(state, system_name, rom_name, create=False):
    """
    Return (stored_rom_key, entry) with case-insensitive ROM-name matching.

    The original ROM filename is retained in JSON for readability.
    """
    systems = state.setdefault("systems", {})
    system_bucket = systems.get(system_name)

    if not isinstance(system_bucket, dict):
        if not create:
            return None, None
        system_bucket = {}
        systems[system_name] = system_bucket

    wanted = rom_name.casefold()
    for stored_name, entry in list(system_bucket.items()):
        if str(stored_name).casefold() == wanted:
            if not isinstance(entry, dict):
                if not create:
                    return stored_name, None
                entry = {}
                system_bucket[stored_name] = entry
            return stored_name, entry

    if not create:
        return None, None

    entry = {
        "failure_sessions": 0,
        "blacklisted": False,
    }
    system_bucket[rom_name] = entry
    return rom_name, entry

def _persistent_blacklisted_roms(state):
    result = {}
    systems = state.get("systems", {})
    if not isinstance(systems, dict):
        return result

    for system_name, roms in systems.items():
        if not isinstance(roms, dict):
            continue
        for rom_name, entry in roms.items():
            if (
                isinstance(entry, dict)
                and bool(entry.get("blacklisted", False))
            ):
                result.setdefault(str(system_name), set()).add(
                    str(rom_name)
                )
    return result

def _persistent_whitelisted_roms(state):
    """
    Convert whitelist JSON to {system_name: set(rom_file_name)}.

    Invalid entries are ignored instead of preventing screen-saver startup.
    """
    result = {}
    systems = state.get("systems", {})
    if not isinstance(systems, dict):
        return result

    for system_name, roms in systems.items():
        if not isinstance(roms, list):
            continue
        cleaned = {
            str(rom_name)
            for rom_name in roms
            if str(rom_name).strip()
        }
        if cleaned:
            result[str(system_name)] = cleaned
    return result

def _rom_in_name_map(name_map, system_name, rom_name):
    """
    Case-insensitive system + ROM filename membership check.
    """
    wanted_system = str(system_name).casefold()
    wanted_rom = str(rom_name).casefold()

    for stored_system, rom_names in name_map.items():
        if str(stored_system).casefold() != wanted_system:
            continue
        return any(
            str(stored_rom).casefold() == wanted_rom
            for stored_rom in rom_names
        )
    return False

def _apply_persistent_whitelist(blacklisted, whitelisted):
    """
    Return effective persistent blacklist after whitelist overrides.

    Session-only quarantine is intentionally not processed here. If a
    whitelisted ROM crashes in the current screen-saver session, it is still
    quarantined until that session ends.
    """
    effective = {}
    rescued = 0

    for system_name, rom_names in blacklisted.items():
        kept = set()
        for rom_name in rom_names:
            if _rom_in_name_map(
                whitelisted,
                system_name,
                rom_name,
            ):
                rescued += 1
            else:
                kept.add(rom_name)

        if kept:
            effective[system_name] = kept

    return effective, rescued

def _record_persistent_rom_failure(
    state,
    path,
    session_id,
    threshold_sessions,
    system_name,
    rom_name,
    phase,
    failure_kind,
):
    """
    Record at most one strike per ROM per screen-saver session.

    Returns:
        (failure_sessions, newly_blacklisted, already_recorded_this_session)
    """
    stored_name, entry = _persistent_entry_for_rom(
        state,
        system_name,
        rom_name,
        create=True,
    )
    if entry is None:
        return 0, False, False

    previous_session = str(entry.get("last_session_id", ""))
    if previous_session == session_id:
        return int(entry.get("failure_sessions", 0)), False, True

    failure_sessions = max(
        0,
        int(entry.get("failure_sessions", 0)),
    ) + 1

    already_blacklisted = bool(entry.get("blacklisted", False))
    newly_blacklisted = (
        not already_blacklisted
        and failure_sessions >= threshold_sessions
    )

    now_iso = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()

    entry["failure_sessions"] = failure_sessions
    entry["last_session_id"] = session_id
    entry["last_failure_utc"] = now_iso
    entry["last_phase"] = str(phase)
    entry["last_failure_kind"] = str(failure_kind)

    if not entry.get("first_failure_utc"):
        entry["first_failure_utc"] = now_iso

    if newly_blacklisted:
        entry["blacklisted"] = True
        entry["blacklisted_utc"] = now_iso

    _save_persistent_rom_state(path, state)
    return failure_sessions, newly_blacklisted, False

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
