"""ROM list lookup and state projection, without file I/O.

Keep existing distinctions: entry lookup matches ROM names case-insensitively
within an exact system key, while whitelist membership casefolds both names.
Entry lookup may create the systems dictionary even when create is false.
"""

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


import json


def load_session_safety(environ, quarantine_key, disabled_key):
    """
    Load supervisor-owned safety state into a worker.

    State is intentionally session-only. It lives in supervisor memory and is
    passed to each replacement worker via environment variables. Closing the
    screen saver discards it completely.
    """
    quarantine = {}
    disabled = set()

    raw_quarantine = environ.get(quarantine_key, "").strip()
    if raw_quarantine:
        try:
            parsed = json.loads(raw_quarantine)
            if isinstance(parsed, dict):
                for system_name, rom_names in parsed.items():
                    if not isinstance(rom_names, list):
                        continue
                    quarantine[str(system_name)] = {
                        str(name).casefold()
                        for name in rom_names
                        if str(name).strip()
                    }
        except Exception as exc:
            print(
                f"[session-safety] could not parse ROM quarantine: {exc}",
                flush=True,
            )

    raw_disabled = environ.get(
        disabled_key,
        "",
    ).strip()
    if raw_disabled:
        try:
            parsed = json.loads(raw_disabled)
            if isinstance(parsed, list):
                disabled = {
                    str(name)
                    for name in parsed
                    if str(name).strip()
                }
        except Exception as exc:
            print(
                f"[session-safety] could not parse suspended systems: {exc}",
                flush=True,
            )

    return quarantine, disabled
