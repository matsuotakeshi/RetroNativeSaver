"""Explicit in-saver list edits. Reload, validate, back up, then atomically save."""
import datetime
import json
import os
from pathlib import Path
import tempfile
import uuid

from rom_list_editor import read_state
from rom_list_policy import _persistent_entry_for_rom, _persistent_whitelisted_roms


def save_checked(path, data, original):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name+'.', suffix='.tmp', delete=False) as f:
            temporary = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        if (path.read_bytes() if path.exists() else None) != original:
            raise RuntimeError(f'{path.name}: another edit detected; try again')
        if original is not None:
            stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup = path.with_name(path.name+f'.{stamp}.{uuid.uuid4().hex[:8]}.bak')
            with backup.open('xb') as f:
                f.write(original)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def blacklist_rom(black_path, white_path, seed_path, system_name, rom_name):
    black, black_raw = read_state(black_path, 'black')
    white, white_raw = read_state(white_path, 'white')
    if white_raw is None and seed_path and Path(seed_path).exists():
        white, _ = read_state(seed_path, 'white')
    # Match every case variant; the explicit user action must not be rescued
    # by an existing whitelist entry on the next saver launch.
    removed = 0
    for name, roms in white['systems'].items():
        if name.casefold() == system_name.casefold():
            kept = [r for r in roms if r.casefold() != rom_name.casefold()]
            removed += len(roms)-len(kept)
            white['systems'][name] = kept
    stored = next((s for s in black['systems'] if s.casefold() == system_name.casefold()), system_name)
    _, entry = _persistent_entry_for_rom(black, stored, rom_name, create=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry.update(blacklisted=True, manual_blacklisted=True, manual_blacklisted_utc=now)
    entry.setdefault('blacklisted_utc', now)
    # Do not invent crashes or overwrite the existing failure evidence.
    # Black first, white second: if the second commit fails, the whitelist
    # still rescues this ROM. The caller reports failure and keeps the tile.
    save_checked(black_path, black, black_raw)
    if removed:
        save_checked(white_path, white, white_raw)
    return black, _persistent_whitelisted_roms(white)


def add_favorite(path, system, rom, catalogs):
    from favorites import validate_favorites, favorite_candidates
    path = Path(path)
    raw = path.read_bytes() if path.exists() else None
    data = json.loads(raw.decode('utf-8-sig')) if raw is not None else {'enabled': True, 'items': []}
    clean = validate_favorites(data)
    # Use the same basename/absolute path/junction rules as runtime selection.
    matched = favorite_candidates([system], catalogs, dict(clean, enabled=True), log=lambda _: None)
    if any(p == rom for _, p in matched):
        return False
    data.setdefault('items', []).append({'system': system['id'], 'rom': str(rom.resolve())})
    save_checked(path, data, raw)
    return True


def remove_favorite(path, system, rom, catalogs):
    """Remove every registration matching this ROM, preserving unrelated data."""
    from favorites import validate_favorites, favorite_candidates
    path = Path(path)
    raw = path.read_bytes() if path.exists() else None
    if raw is None:
        return False
    data = json.loads(raw.decode('utf-8-sig'))
    validate_favorites(data)
    kept, matches = [], {}
    for item in data.get('items', []):
        # Keep the original entries, including unknown fields and auto inputs.
        key = (item['system'].strip().casefold(), item['rom'].strip().replace('\\', '/').casefold())
        if key not in matches:
            if key[0] != str(system['id']).casefold():
                matches[key] = False
            else:
                clean = validate_favorites({'items': [item]})
                matched = favorite_candidates([system], catalogs, clean, log=lambda _: None)
                matches[key] = any(p == rom for _, p in matched)
        if not matches[key]:
            kept.append(item)
    if len(kept) == len(data.get('items', [])):
        return False
    data['items'] = kept
    save_checked(path, data, raw)
    return True


def refresh_safety(safety):
    """Manual edits happen in the scheduler; its supervisor must not save stale state."""
    try:
        black, _ = read_state(safety.persistent_rom_blacklist_path, 'black')
        white = {'systems': {}}
        if safety.persistent_rom_whitelist_enabled:
            white, raw = read_state(safety.persistent_rom_whitelist_path, 'white')
            if raw is None and safety.persistent_rom_whitelist_seed_path.exists():
                white, _ = read_state(safety.persistent_rom_whitelist_seed_path, 'white')
    except (OSError, ValueError) as exc:
        print(f'[saver-control] cannot refresh persistent lists: {exc}; keeping session safety', flush=True)
        return False
    whitelisted = _persistent_whitelisted_roms(white)
    safety.persistent_rom_state = black
    safety.persistent_whitelisted = whitelisted
    # A persistent/manual exclusion is not evidence of a current-session crash.
    # Do not merge it into the session quarantine sent to replacement workers.
    return True


def record_failure_with_fresh_lists(safety, snapshot, watchdog):
    enabled = safety.persistent_rom_blacklist_enabled
    if not refresh_safety(safety):
        # Still quarantine crashes in memory, but do not overwrite a file we
        # could not read with a stale copy retained by the parent process.
        safety.persistent_rom_blacklist_enabled = False
    try:
        safety.record_runtime_failure(snapshot, watchdog)
    finally:
        safety.persistent_rom_blacklist_enabled = enabled

