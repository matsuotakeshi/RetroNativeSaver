"""Title metadata without Win32, emulator or UI initialization.

Runtime and favorites intentionally retain separate lookup policies: lower vs
casefold, permissive vs string-only JSON values, and stem vs filename fallback.
Only the identical JSON envelope handling is shared between those policies.
"""
import glob
import json
import os
from pathlib import Path


def _title_payload(data):
    if isinstance(data, dict) and isinstance(data.get('titles'), dict):
        return data['titles']
    return data


def _playlist_title(item, filters, roots):
    """Apply the existing core-or-path filter and normalize one playlist entry."""
    if not isinstance(item, dict):
        return None

    core_name = str(item.get("core_name", "")).lower()
    core_path = str(item.get("core_path", "")).lower()
    rom_path = item.get("path")

    core_match = (
        not filters
        or any(f in core_name or f in core_path for f in filters)
    )

    path_match = False
    if rom_path and roots:
        try:
            normalized_rom = os.path.normcase(
                os.path.normpath(
                    os.path.expandvars(str(rom_path).split("#", 1)[0])
                )
            )
            path_match = any(
                normalized_rom == root
                or normalized_rom.startswith(root + os.sep)
                for root in roots
            )
        except Exception:
            path_match = False

    if not core_match and not path_match:
        return None

    label = str(item.get("label", "")).strip()
    if not rom_path or not label or label.upper() == "DETECT":
        return None

    nk = _title_key(rom_path)
    return (nk, label) if nk else None


def _title_key(value) -> str:
    """Normalize ROM/archive path or shortname to a title lookup key."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""

    # RetroArch paths can contain archive-member syntax.
    raw = raw.split("#", 1)[0]
    raw = raw.replace("\\", "/")
    name = raw.rsplit("/", 1)[-1]

    # Path.stem works for normal ROM/archive names.
    try:
        stem = Path(name).stem
    except Exception:
        stem = name.rsplit(".", 1)[0] if "." in name else name

    return stem.strip().lower()


def _load_title_json(path: Path) -> dict[str, str]:
    result = {}
    if not path.exists():
        return result

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print(f"[titles] ERROR reading {path}: {exc}", flush=True)
        return result

    # Accept either a plain {shortname:title} object or {"titles": {...}}.
    data = _title_payload(data)

    if not isinstance(data, dict):
        return result

    for key, value in data.items():
        nk = _title_key(key)
        title = str(value).strip() if value is not None else ""
        if nk and title:
            result[nk] = title

    return result


def _load_retroarch_playlist_titles(patterns, core_name_filters=None, path_roots=None) -> dict[str, str]:
    """
    Build shortname -> display label mappings from RetroArch .lpl playlists.

    RetroArch playlists already contain human-readable labels, so this gives
    FBNeo/MAME-style arcade shortnames proper display titles without requiring
    the standalone emulator at screen-saver runtime.
    """
    result = {}
    filters = [
        str(x).lower()
        for x in (core_name_filters or [])
        if str(x).strip()
    ]
    roots = [
        os.path.normcase(os.path.normpath(os.path.expandvars(str(x))))
        for x in (path_roots or [])
        if str(x).strip()
    ]

    seen_files = set()
    for pattern in patterns or []:
        expanded = os.path.expandvars(str(pattern))
        for filename in glob.glob(expanded):
            p = Path(filename)
            keyfile = str(p).lower()
            if keyfile in seen_files or not p.is_file():
                continue
            seen_files.add(keyfile)

            try:
                playlist = json.loads(p.read_text(encoding="utf-8-sig"))
            except Exception:
                continue

            items = playlist.get("items", []) if isinstance(playlist, dict) else []
            if not isinstance(items, list):
                continue

            for item in items:
                entry = _playlist_title(item, filters, roots)
                if entry is not None:
                    nk, label = entry
                    if nk not in result:
                        result[nk] = label

    return result


def build_title_maps(systems, app_dir: Path) -> dict[str, dict[str, str]]:
    """
    Load title mappings once per worker.

    Sources, in priority order:
      1) title_db JSON (canonical cached overrides)
      2) RetroArch .lpl title_sources (fills missing entries only)
    """
    maps = {}

    for system in systems:
        sid = str(system.get("id", "")).strip()
        if not sid:
            continue

        merged = {}

        db_name = system.get("title_db")
        if db_name:
            db_path = Path(str(db_name))
            if not db_path.is_absolute():
                db_path = app_dir / db_path
            merged.update(_load_title_json(db_path))

        playlist_titles = _load_retroarch_playlist_titles(
            system.get("title_sources", []),
            system.get("title_core_names", []),
            system.get("title_path_roots", []),
        )
        for key, value in playlist_titles.items():
            merged.setdefault(key, value)

        if merged:
            maps[sid] = merged
            print(
                f"[titles] [{system.get('name', sid)}] "
                f"{len(merged)} title(s) loaded",
                flush=True,
            )

    return maps


def resolve_display_title(system: dict, rom_path: Path, title_maps) -> str:
    shortname = Path(rom_path).stem
    sid = str(system.get("id", ""))
    mapping = title_maps.get(sid, {})
    return mapping.get(_title_key(rom_path), shortname)


# Favorites editor policy (kept distinct for compatibility).
def title_key(value):
    name = str(value).split('#', 1)[0].replace('\\', '/').rsplit('/', 1)[-1]
    return Path(name).stem.strip().casefold()


def title_database(system):
    defaults = {'arcade': 'fbneo', 'fbneo': 'fbneo', 'mame': 'mame'}
    sid = str(system.get('id', '')).casefold()
    return system.get('title_db') or (
        f'metadata/{defaults[sid]}_titles.json' if sid in defaults else None)


def load_titles(app_dir, system):
    name = title_database(system)
    if not name:
        return {}
    path = Path(os.path.expandvars(str(name)))
    if not path.is_absolute():
        path = Path(app_dir) / path
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        data = _title_payload(data)
        if not isinstance(data, dict):
            return {}
        return {title_key(k): v.strip() for k, v in data.items()
                if isinstance(v, str) and v.strip()}
    except (OSError, ValueError):
        return {}


def display_title(rom, titles):
    return titles.get(title_key(rom), str(rom).replace('\\', '/').rsplit('/', 1)[-1])
