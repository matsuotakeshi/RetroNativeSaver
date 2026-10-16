"""Optional dense presentation; reuse the normal per-tile scheduler and safety.

The supervisor freezes the presentation/group members in its config snapshot.
Worker restarts cannot redraw the lottery. System settings remain independently
editable, and the chosen system is copied before adjusting tile capacity.
"""
import math
from pathlib import Path
import random

DEFAULT_GROUPS = (
    ('megadrive', 'megacd'), ('pcengine', 'pcenginecd', 'pcfx'), ('gb', 'gbc', 'gba'),
    ('fds', 'nes'), ('snes',), ('fbneo',),
    ('msx', 'x1', 'x68000', 'pc88', 'pc98'), ('neocd',),
)
SUPPORTED = tuple(sid for group in DEFAULT_GROUPS for sid in group)
SESSION_KEY = '_single_system_session'
MAX_TILES = 64
FBNEO_MAX_TILES = 32


def presentation_probability(options):
    """New relative weights take precedence; v0.21.15 probability still works."""
    if 'normal_weight' in options or 'grouped_weight' in options:
        normal, grouped = options.get('normal_weight'), options.get('grouped_weight')
        for value in (normal, grouped):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('normal_weight and grouped_weight must be finite nonnegative numbers')
        scale = max(normal, grouped)
        if scale == 0:
            raise ValueError('at least one presentation weight must be positive')
        return (grouped / scale) / (normal / scale + grouped / scale)
    probability = options.get('probability', .5)
    if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('probability must be a number from 0 to 1')
    return probability


def configured_groups(options):
    """Use explicit groups, or retain singleton semantics of old systems lists."""
    disabled = options.get('disabled_systems', [])
    if not isinstance(disabled, list) or any(sid not in (*SUPPORTED, 'cdrom2') for sid in disabled):
        raise ValueError('disabled_systems must be a list of supported system IDs')
    disabled = {'pcenginecd' if sid == 'cdrom2' else sid for sid in disabled}
    if 'groups' in options:
        groups = options['groups']
    elif 'systems' in options:
        if not isinstance(options['systems'], list):
            raise ValueError('systems must be a list')
        groups = [[sid] for sid in options['systems']]
    else:
        groups = [list(group) for group in DEFAULT_GROUPS]
    if not isinstance(groups, list):
        raise ValueError('groups must be a list of system lists')
    result = []
    for group in groups:
        if not isinstance(group, list) or not group:
            raise ValueError('each group must be a nonempty list')
        members = []
        for sid in group:
            if sid == 'cdrom2':
                sid = 'pcenginecd'
            if sid not in SUPPORTED:
                raise ValueError(f'unsupported grouped system: {sid!r}')
            if sid not in disabled and sid not in members:
                members.append(sid)
        if members and members not in result:
            result.append(members)
    return result


def prepare_session(cfg, app_dir, args, launch_mode, *, reuse=False, rng=None):
    if reuse and SESSION_KEY in cfg:
        return cfg
    # Discard internal session data from an on-disk config or inherited launch.
    result = {key: value for key, value in cfg.items() if key != SESSION_KEY}
    requested = getattr(args, 'presentation', 'auto')
    from system_config import display_mode
    preview, fullscreen = display_mode(launch_mode, result, args)
    if preview or not result.get('independent_slots_enabled', False) or requested == 'normal':
        return result
    if requested == 'auto' and (not fullscreen or args.system or args.slots is not None):
        return result  # Keep existing diagnostic/windowed commands predictable.
    options = result.get('single_system_mode', {})
    if not isinstance(options, dict):
        print('[presentation] invalid single_system_mode; using normal mode', flush=True)
        return result
    if requested == 'auto' and options.get('enabled', False) is not True:
        return result
    result[SESSION_KEY] = None  # Freeze a normal-mode draw too.
    try:
        probability = presentation_probability(options)
        groups = configured_groups(options)
        wanted = {sid for group in groups for sid in group}
    except (ValueError, TypeError, OverflowError) as exc:
        print(f'[presentation] invalid settings: {exc}; using normal mode', flush=True)
        return result
    rng = rng if rng is not None else random.SystemRandom()
    if requested == 'auto' and rng.random() >= probability:
        print('[presentation] session=normal', flush=True)
        return result
    from system_config import load_system_configs, apply_cli_system_overrides
    systems = apply_cli_system_overrides(load_system_configs(Path(app_dir) / result.get('systems_dir', 'systems')), args)
    eligible = []
    for system in systems:
        sid = system.get('id')
        core = Path(system.get('core', ''))
        if not core.is_absolute():
            core = Path(app_dir) / core
        if (sid in wanted and sid not in eligible and system.get('enabled', True)
                and str(system.get('render_backend', 'software')).lower() == 'software'
                and core.is_file() and Path(system.get('rom_dir', '')).is_dir()):
            eligible.append(sid)
    candidates = [[sid for sid in group if sid in eligible] for group in groups]
    candidates = [group for group in candidates if group]
    if candidates:
        if 'systems' in options and 'groups' not in options:
            result[SESSION_KEY] = rng.choice([group[0] for group in candidates])
        else:
            result[SESSION_KEY] = list(rng.choice(candidates))
        print(f'[presentation] session=single-system group={result[SESSION_KEY]}', flush=True)
    else:
        print('[presentation] no available configured group; using normal mode', flush=True)
    return result


def selected_systems(cfg, systems, catalogs):
    members = cfg.get(SESSION_KEY)
    if members is None:
        return None
    if isinstance(members, str):
        members = [members]  # Existing singleton snapshot/config compatibility.
    chosen = [system for system in systems if system.get('id') in members
              and system.get('enabled', True) and catalogs.get(system['id'])]
    if chosen:
        return chosen
    # A suspended member can disappear, but never introduce another group.
    raise RuntimeError(f'Grouped session {members} has no available ROMs/system; stopping saver')


def tile_limit(systems):
    return FBNEO_MAX_TILES if {s['id'] for s in systems} == {'fbneo'} else MAX_TILES


def monitor_slots(monitor_rects, virtual_left, virtual_top, gap_pixels=0, *, systems=()):
    """Resolution-based rules, independent of Windows primary/order/origin."""
    from screen_layout import _cell_rect
    limit = tile_limit(systems)
    plans = []
    for left, top, right, bottom in monitor_rects:
        width, height = right-left, bottom-top
        if width <= 0 or height <= 0:
            return None
        if limit == FBNEO_MAX_TILES:
            cols, rows = 4, 4
        else:
            cols, rows = (9, 4) if (width, height) == (2560, 1080) else (7, 4)
        plans.append((left-virtual_left, top-virtual_top, width, height, cols, rows))
    if not plans or sum(cols*rows for _, _, _, _, cols, rows in plans) > limit:
        print(f'[presentation] layout exceeds {limit} tiles; using normal layout/mode', flush=True)
        return None
    rects = []
    for left, top, width, height, cols, rows in plans:
        print(f'[display] single-system monitor {width}x{height} layout={cols}x{rows}', flush=True)
        for row in range(rows):
            for col in range(cols):
                rects.append(_cell_rect(left+width*col//cols, top+height*row//rows,
                                        left+width*(col+1)//cols, top+height*(row+1)//rows, gap_pixels))
    return rects


def scheduler_inputs(systems, catalogs, count):
    """Raise only this session's machine cap; keep resource groups and settings."""
    if isinstance(systems, dict):
        systems = [systems]
    limit = tile_limit(systems)
    if not 1 <= count <= limit:
        raise ValueError(f'Grouped tile count must be between 1 and {limit}')
    from fixed_rom_catalog import filtered_catalogs
    chosen = [dict(system, max_concurrent=min(count, FBNEO_MAX_TILES) if system['id'] == 'fbneo' else count)
              for system in systems]
    # No mutation of the loaded system dict or original JSON. This also restricts
    # favorite matching, replacement retries and UI actions to the same hardware.
    return chosen, filtered_catalogs(catalogs, {s['id']: catalogs[s['id']] for s in chosen})


def scheduler_config(cfg):
    """Dense tiles use pixel scaling and a display cap, not slower emulation."""
    value = cfg.get('single_system_mode', {}).get('max_fps', 25)
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('max_fps must be finite and positive')
        cap = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        print(f'[presentation] invalid max_fps: {exc}; using 25', flush=True)
        cap = 25.
    result = dict(cfg, _single_system_rendering=True,
                  independent_max_fps=min(cap, float(cfg.get('independent_max_fps', 30))))
    overrides = cfg.get('single_system_mode', {}).get('resource_groups', {})
    if not isinstance(overrides, dict):
        raise ValueError('single_system_mode.resource_groups must be an object')
    if overrides:
        existing = cfg.get('resource_groups', {})
        groups = dict(existing) if isinstance(existing, dict) else {}
        for name, setting in overrides.items():
            value = setting.get('max_weight') if isinstance(setting, dict) else None
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError('grouped resource max_weight must be a positive integer')
            previous = groups.get(name, {})
            groups[name] = dict(previous if isinstance(previous, dict) else {}, max_weight=value)
        result['resource_groups'] = groups
    return result
