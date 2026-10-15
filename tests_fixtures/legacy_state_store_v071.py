"""Frozen v0.20.71 file operations, for tests only."""
import json
import os

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
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("root is not an object")
        systems = raw.get("systems")
        if not isinstance(systems, dict):
            raw["systems"] = {}
        raw["version"] = int(raw.get("version", 1))
        return raw
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
    return {
        "version": 1,
        "systems": {},
    }

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
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_name(
                f"{path.name}.tmp.{os.getpid()}"
            )
            tmp_path.write_text(
                json.dumps(
                    seed_raw,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            os.replace(tmp_path, path)
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
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("root is not an object")
        systems = raw.get("systems")
        if not isinstance(systems, dict):
            raw["systems"] = {}
        raw["version"] = int(raw.get("version", 1))
        return raw
    except Exception as exc:
        print(
            f"[persistent-safety] could not read whitelist "
            f"{path}: {exc}; using empty whitelist",
            flush=True,
        )
        return _empty_persistent_rom_whitelist()
