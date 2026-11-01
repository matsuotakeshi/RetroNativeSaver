"""Manually refreshed ROM scan results; runtime safety filters remain live."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

FORMAT = 1  # Bump if scanning/canonicalization semantics change.
SCAN_KEYS = ('rom_dir', 'extensions', 'recursive', 'validate_archive_contents',
             'disk_boot_mode', 'archive_mode', 'content_extensions', 'exclude_name_contains')


class Catalogs(dict):
    """Only paths in this dictionary are eligible; canonical paths are hints."""
    def __init__(self, values=(), canonical_paths=None):
        super().__init__(values)
        self.canonical_paths = canonical_paths if canonical_paths is not None else {}


def filtered_catalogs(source, values):
    if isinstance(source, Catalogs):
        return Catalogs(values, source.canonical_paths)
    return values


def signature(system):
    values = {key: system[key] for key in SCAN_KEYS if key in system}
    if not Path(system['rom_dir']).is_absolute():
        values['relative_to'] = os.getcwd()
    return values


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def read_catalog(path):
    """Invalid or absent file falls back to live scanning, never partial data."""
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('format') != FORMAT
                or not isinstance(data.get('systems'), dict)
                or data.get('sha256') != digest(data['systems'])):
            raise ValueError('format or checksum mismatch')
        for item in data['systems'].values():
            if (not isinstance(item, dict) or not isinstance(item.get('signature'), dict)
                    or not isinstance(item.get('roms'), list)):
                raise ValueError('invalid system entry')
            if any(not isinstance(pair, list) or len(pair) != 2
                   or not all(isinstance(p, str) and p for p in pair) for pair in item['roms']):
                raise ValueError('invalid ROM entry')
        return data['systems']
    except (OSError, ValueError, RecursionError) as exc:
        print(f'[fixed-catalog] unavailable: {path}: {exc}; using live scan; run update_rom_catalog.bat', flush=True)
        return {}


def cached_roms(system, saved, catalogs):
    """None means scan; [] means a valid empty catalog, not a cache miss."""
    item = saved.get(system['id'])
    system.pop('_fixed_rom_catalog', None)
    if item is None or item['signature'] != signature(system):
        if saved:
            print(f"[fixed-catalog] [{system['id']}] missing/changed scan settings; using live scan; run update_rom_catalog.bat", flush=True)
        return None
    # One root check, not a file-by-file scan. Missing media must not be selected.
    if not Path(system['rom_dir']).is_dir():
        print(f"[fixed-catalog] [{system['id']}] ROM directory unavailable", flush=True)
        return []
    roms = [Path(pair[0]) for pair in item['roms']]
    if system['id'] == 'msx':
        # Filter old snapshots in memory without a rescan or format change.
        from rom_catalog import is_msx_boot_candidate
        roms = [path for path in roms if is_msx_boot_candidate(system, path)]
        removed = len(item['roms']) - len(roms)
        if removed:
            print(f"[fixed-catalog] [{system['id']}] secondary disks omitted={removed}", flush=True)
    catalogs.canonical_paths.update(item['roms'])
    system['_fixed_rom_catalog'] = True
    print(f"[fixed-catalog] [{system['id']}] loaded {len(roms)} ROM(s)", flush=True)
    return roms


def write_catalog(path, systems, progress=None):
    """Rescan completely; replace the old file only after a successful write."""
    from catalog_paths import CatalogPaths
    from rom_catalog import scan_roms
    from startup_timing import span
    saved = {}
    for system in systems:
        if not system.get('enabled', True):
            continue
        if str(system.get('render_backend', 'software')).lower() not in ('software', 'opengl', 'glcore'):
            continue
        sid = system['id']
        if sid in saved:
            raise ValueError(f'Duplicate system id: {sid}')
        if not Path(system['rom_dir']).is_dir():
            raise OSError(f"ROM directory unavailable: {system['rom_dir']}; previous catalog kept")
        print(f'[fixed-catalog] updating [{sid}]', flush=True)
        with span('fixed_catalog_update_scan', system=sid):
            roms = scan_roms(system, progress=progress)
        paths = CatalogPaths()
        with span('fixed_catalog_update_paths', system=sid):
            saved[sid] = dict(signature=signature(system),
                              roms=[[str(p), paths.canonical(p)] for p in roms])
    data = dict(format=FORMAT, systems=saved, sha256=digest(saved))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name+'.', suffix='.tmp', delete=False) as f:
            name = f.name
            json.dump(data, f, ensure_ascii=True, separators=(',', ':'))
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()
    count = sum(len(item['roms']) for item in saved.values())
    print(f'[fixed-catalog] complete: {path}; systems={len(saved)} ROMs={count}', flush=True)
    return count


def update_from_config(app_dir, cfg):
    folder = Path(app_dir) / cfg.get('systems_dir', 'systems')
    if not folder.is_dir():
        raise OSError(f'Systems directory unavailable: {folder}')
    # The interactive updater rejects malformed JSON rather than replacing a
    # good catalog with an accidentally incomplete set of systems.
    systems = []
    for path in sorted(folder.glob('*.json')):
        system = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(system, dict) or not isinstance(system.get('id'), str):
            raise ValueError(f'Invalid system: {path}')
        systems.append(system)
    if not systems:
        raise ValueError(f'No systems found: {folder}')
    return write_catalog(Path(app_dir)/'state/rom_catalog.json', systems)


def run_update_command(app_dir, argv):
    import argparse
    from launch_options import load_config
    parser = argparse.ArgumentParser(description='Update the fixed ROM catalog without starting emulators.')
    parser.add_argument('--update-rom-catalog', action='store_true')
    parser.add_argument('--config', default=str(Path(app_dir)/'config.json'))
    args = parser.parse_args(argv)
    try:
        update_from_config(app_dir, load_config(args.config))
    except Exception as exc:
        print(f'[fixed-catalog] update failed; previous catalog kept: {exc}', flush=True)
        return 1
    return 0
