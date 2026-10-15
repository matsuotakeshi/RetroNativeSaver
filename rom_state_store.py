"""Persistent ROM-list file I/O with the existing recovery policies.

UTF-8 (not utf-8-sig), PID temp names, replace order, log text, and the different
cleanup behavior of state saving and whitelist seeding are intentional here.
This extraction does not add multi-writer synchronization.
"""
import json
import os


def _read_state_json(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("root is not an object")
    systems = raw.get("systems")
    if not isinstance(systems, dict):
        raw["systems"] = {}
    raw["version"] = int(raw.get("version", 1))
    return raw


def _write_state_json(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(
        f"{path.name}.tmp.{os.getpid()}"
    )
    tmp_path.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def _empty_persistent_rom_state():
    return {
        "version": 1,
        "systems": {},
    }


def _load_persistent_rom_state(path):
    """
    Load cross-session ROM failure evidence / blacklist state.

    This file is supervisor-owned. A parse/read failure never prevents the
    screen saver from starting; session-only crash containment still works.
    """
    if path is None or not path.exists():
        return _empty_persistent_rom_state()

    try:
        return _read_state_json(path)
    except Exception as exc:
        print(
            f"[persistent-safety] could not read {path}: {exc}; "
            "starting with empty persistent state",
            flush=True,
        )
        return _empty_persistent_rom_state()


def _save_persistent_rom_state(path, state):
    """
    Atomically persist blacklist/evidence state.

    Failure to save is logged but is never fatal to the screen saver.
    """
    if path is None:
        return False

    try:
        _write_state_json(path, state)
        return True
    except Exception as exc:
        print(
            f"[persistent-safety] could not save {path}: {exc}",
            flush=True,
        )
        try:
            tmp_path = path.with_name(
                f"{path.name}.tmp.{os.getpid()}"
            )
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False


def _empty_persistent_rom_whitelist():
    return _empty_persistent_rom_state()


def _load_persistent_rom_whitelist(path, seed_path=None):
    """
    Load persistent ROM whitelist.

    Format:
        {
          "version": 1,
          "systems": {
            "Nintendo 64": [
              "Mario Kart 64 (Japan).n64"
            ]
          }
        }

    If the user's whitelist does not exist yet, optionally seed it from the
    packaged default file. Existing user files are never overwritten.
    """
    if path is None:
        return _empty_persistent_rom_whitelist()

    if not path.exists() and seed_path is not None and seed_path.exists():
        try:
            seed_raw = json.loads(seed_path.read_text(encoding="utf-8"))
            if not isinstance(seed_raw, dict):
                raise ValueError("seed root is not an object")
            _write_state_json(path, seed_raw)
            print(
                f"[persistent-safety] seeded whitelist from "
                f"{seed_path} -> {path}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[persistent-safety] could not seed whitelist "
                f"from {seed_path}: {exc}",
                flush=True,
            )

    if not path.exists():
        return _empty_persistent_rom_whitelist()

    try:
        return _read_state_json(path)
    except Exception as exc:
        print(
            f"[persistent-safety] could not read whitelist "
            f"{path}: {exc}; using empty whitelist",
            flush=True,
        )
        return _empty_persistent_rom_whitelist()


import datetime
from rom_list_policy import _persistent_entry_for_rom


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
