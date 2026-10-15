"""Two comparison functions only; origin v0.20.107."""
from pathlib import Path
from pc88_disks import playlist_disks, identity, NON_BOOT

def favorite_candidates(systems, catalogs, data, log=print):
    """Match only the already-filtered runtime catalog. Never bypass safety filters."""
    if not data.get('enabled', True):
        return []
    by_id = {str(s['id']).casefold(): s for s in systems}
    result, seen = [], set()
    canonical_catalogs = {}

    def canonical(path):
        try:
            return str(Path(path).resolve()).replace('\\', '/').casefold()
        except (OSError, RuntimeError):
            return str(path).replace('\\', '/').casefold()

    for item in data.get('items', []):
        system = by_id.get(item['system'].casefold())
        if system is None:
            log(f"[favorites] unavailable system: {item['system']}")
            continue
        wanted = item['rom'].replace('\\', '/').casefold()
        # A bare basename must identify exactly one ROM in this system.
        matches = [p for p in catalogs.get(system['id'], []) if (
            p.name.casefold() == wanted if '/' not in wanted
            else str(p).replace('\\', '/').casefold() == wanted
        )]
        if not matches and '/' in wanted:
            sid = system['id']
            if sid not in canonical_catalogs:
                index = {}
                for rom in catalogs.get(sid, []):
                    index.setdefault(canonical(rom), []).append(rom)
                canonical_catalogs[sid] = index
            matches = canonical_catalogs[sid].get(canonical(item['rom']), [])
        if len(matches) != 1:
            log(f"[favorites] unavailable or ambiguous (missing/filtered): [{system['id']}] {item['rom']}")
            continue
        rom = matches[0]
        key = (system['id'], str(rom).casefold())
        if key not in seen:
            seen.add(key)
            result.append((system, rom))
    return result

def boot_candidates(paths):
    referenced = set()
    invalid = set()
    for path in paths:
        if path.suffix.lower() == '.m3u':
            try:
                referenced.update(p.resolve() for p in playlist_disks(path))
            except (OSError, ValueError) as exc:
                invalid.add(path)
                print(f'[pc88] invalid playlist: {exc}', flush=True)
    result = []
    for path in paths:
        if path in invalid or path.resolve() in referenced:
            continue
        info = identity(path)
        if info is not None and info[2] != 1:
            continue
        if NON_BOOT.search(path.stem):
            continue
        result.append(path)
    return result
