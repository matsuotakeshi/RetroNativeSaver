"""Frozen v0.20.64 behavior for compatibility tests; not production code."""
import json
import random
from pathlib import Path

def _resource_group_limit(cfg, group_name):
    groups = cfg.get("resource_groups", {})
    if not isinstance(groups, dict):
        return None

    group_cfg = groups.get(group_name)
    if not isinstance(group_cfg, dict):
        return None

    try:
        return max(0, int(group_cfg.get("max_weight", 0)))
    except Exception:
        return None

def _resource_group_info(system):
    group_name = str(system.get("resource_group", "")).strip()
    if not group_name:
        return None, 0

    try:
        weight = max(0, int(system.get("resource_weight", 1)))
    except Exception:
        weight = 1

    return group_name, weight

def _resource_group_can_add(system, group_usage, cfg, replacing_system=None):
    """
    Return True if adding system keeps all configured resource-group budgets.

    replacing_system is used by startup retry fallback. The planned slot's
    resource weight is first removed, then the fallback candidate is tested,
    so a failed ROM cannot silently push a heavy group over budget.
    """
    usage = dict(group_usage or {})

    if replacing_system is not None:
        old_group, old_weight = _resource_group_info(replacing_system)
        if old_group:
            usage[old_group] = max(
                0,
                usage.get(old_group, 0) - old_weight,
            )

    group_name, weight = _resource_group_info(system)
    if not group_name:
        return True

    limit = _resource_group_limit(cfg, group_name)
    if limit is None or limit <= 0:
        return True

    return usage.get(group_name, 0) + weight <= limit

def _resource_group_add_usage(system, group_usage):
    group_name, weight = _resource_group_info(system)
    if group_name:
        group_usage[group_name] = (
            group_usage.get(group_name, 0) + weight
        )

def _resource_group_usage_from_picks(picks):
    usage = {}
    for system, _rom in picks:
        _resource_group_add_usage(system, usage)
    return usage

def choose_slots(systems, catalogs, cfg, count=4, favorites=None):
    """
    Fill slots from enabled systems while respecting both:
      - per-system max_concurrent
      - optional weighted resource-group budgets

    Prefer spreading different systems first, then allow repeats.
    """
    available = [
        s for s in systems
        if bool(s.get("enabled", True))
        and s.get("id") in catalogs
        and catalogs[s["id"]]
        and str(s.get("render_backend", "software")).lower()
            in ("software", "opengl", "glcore")
    ]
    if not available:
        raise RuntimeError(
            "No enabled supported systems with ROMs are available."
        )

    picks = []
    counts = {}
    group_usage = {}

    def can_pick(system):
        sid = system["id"]
        cap = int(system.get("max_concurrent", count))
        if counts.get(sid, 0) >= cap:
            return False
        return _resource_group_can_add(
            system,
            group_usage,
            cfg,
        )

    def add_pick(system, rom):
        sid = system["id"]
        picks.append((system, rom))
        counts[sid] = counts.get(sid, 0) + 1
        _resource_group_add_usage(system, group_usage)

    # Reserve a favorite before random picks consume concurrency/resource budgets.
    available_ids = {system['id'] for system in available}
    favorite_pool = [pair for pair in (favorites or [])
                     if pair[0]['id'] in available_ids and can_pick(pair[0])]
    if favorite_pool and count > 0:
        system, rom = random.choice(favorite_pool)
        add_pick(system, rom)
        print(f"[favorites] reserved slot 1: [{system['id']}] {rom.name}", flush=True)
    elif favorites and count > 0:
        print("[favorites] no favorite fits concurrency/resource limits; using normal selection", flush=True)

    # First pass: spread across systems.
    shuffled = available[:]
    random.shuffle(shuffled)
    for system in shuffled:
        if len(picks) >= count:
            break
        if counts.get(system["id"], 0) or not can_pick(system):
            continue
        sid = system["id"]
        rom = random.choice(catalogs[sid])
        add_pick(system, rom)

    # Second pass: fill remaining slots, respecting all caps/budgets.
    guard = 0
    while len(picks) < count and guard < 1000:
        guard += 1

        eligible = [
            system for system in available
            if can_pick(system)
        ]
        if not eligible:
            break

        system = random.choice(eligible)
        sid = system["id"]

        already = {
            str(r)
            for s, r in picks
            if s["id"] == sid
        }
        candidates = [
            r for r in catalogs[sid]
            if str(r) not in already
        ]
        rom = random.choice(candidates or catalogs[sid])
        add_pick(system, rom)

    if group_usage:
        usage_text = ", ".join(
            f"{group}={used}/{_resource_group_limit(cfg, group)}"
            for group, used in sorted(group_usage.items())
        )
        print(
            f"[resource-group] selected usage: {usage_text}",
            flush=True,
        )

    if len(picks) < count:
        print(
            f"[selector] only {len(picks)} slot(s) could be filled "
            f"(requested {count})"
        )

    return picks

def load_system_configs(systems_dir: Path):
    systems = []
    if not systems_dir.exists():
        raise RuntimeError(f"systems directory not found: {systems_dir}")

    for path in sorted(systems_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_config_path"] = str(path)
            systems.append(data)
        except Exception as exc:
            print(f"[config] ERROR {path.name}: {exc}")

    return systems

def select_slot(index, systems, catalogs, cfg, occupied, favorites, banned, suspended, rng=random, normal_occupied=None):
    """Reservations include loading slots. The replacing slot is already stopped."""
    counts, usage = {}, {}
    for system, rom in occupied:
        sid = system['id']
        counts[sid] = counts.get(sid, 0) + 1
        group = system.get('resource_group')
        if group:
            usage[group] = usage.get(group, 0) + max(0, int(system.get('resource_weight', 1)))
    def allowed(system):
        if not system.get('enabled', True) or system.get('name', system['id']) in suspended:
            return False
        if str(system.get('render_backend', 'software')).lower() not in ('software', 'opengl', 'glcore'):
            return False
        if counts.get(system['id'], 0) >= int(system.get('max_concurrent', 999)):
            return False
        group = system.get('resource_group')
        limit = cfg.get('resource_groups', {}).get(group, {}).get('max_weight', 0)
        return not group or int(limit) <= 0 or usage.get(group, 0) + max(0, int(system.get('resource_weight', 1))) <= int(limit)
    def fits(system, picks):
        sid = system['id']
        if sum(s['id'] == sid for s, _ in picks) >= int(system.get('max_concurrent', 999)):
            return False
        group = system.get('resource_group')
        limit = int(cfg.get('resource_groups', {}).get(group, {}).get('max_weight', 0))
        weight = sum(max(0, int(s.get('resource_weight', 1))) for s, _ in picks
                     if s.get('resource_group') == group)
        return not group or limit <= 0 or weight + max(0, int(system.get('resource_weight', 1))) <= limit

    viable_favorites = [(s, r) for s, r in favorites
                        if s.get('enabled', True) and s.get('name', s['id']) not in suspended
                        and str(s.get('render_backend', 'software')).lower() in ('software', 'opengl', 'glcore')
                        and r in catalogs.get(s['id'], []) and (s['id'], str(r)) not in banned
                        and fits(s, [])]
    pools = {}
    eligible = []
    for system in systems:
        if allowed(system) and (index == 0 or normal_occupied is None or all(
                fits(favorite, list(normal_occupied) + [(system, None)])
                for favorite, _ in viable_favorites)):
            pool = [r for r in catalogs.get(system['id'], [])
                    if (system['id'], str(r)) not in banned]
            if pool:
                eligible.append(system)
                pools[system['id']] = pool
    if index == 0:
        candidates = [(s, r) for s, r in favorites if s['id'] in pools and r in pools[s['id']]]
        if candidates:
            return rng.choice(candidates)
        if viable_favorites:
            # Changed favorites may need existing ordinary tiles to drain first.
            return None
    if not eligible:
        return None
    # Spread systems when capacity permits; don't duplicate a running ROM unless unavoidable.
    system = rng.choice([s for s in eligible if not counts.get(s['id'])] or eligible)
    used = {(s['id'], str(r)) for s, r in occupied}
    pool = pools[system['id']]
    unique = [r for r in pool if (system['id'], str(r)) not in used]
    return system, rng.choice(unique or pool)


def apply_cli_system_overrides(systems, args):
    if args.system:
        wanted = args.system.strip().lower()
        systems = [
            s for s in systems
            if str(s.get("id", "")).lower() == wanted
            or str(s.get("name", "")).lower() == wanted
        ]
        if not systems:
            raise RuntimeError(f"System not found: {args.system}")
        if args.force_system:
            for s in systems:
                s["enabled"] = True

    if args.no_hw_readback:
        for s in systems:
            s["hw_readback"] = False

    if args.env_trace_frames > 0:
        for s in systems:
            s["env_trace_frames"] = args.env_trace_frames

    if args.disable_log_interface:
        for s in systems:
            s["provide_log_interface"] = False

    if args.disable_perf_interface:
        for s in systems:
            s["provide_perf_interface"] = False

    if args.no_frame_rebind:
        for s in systems:
            s["frame_rebind_context"] = False

    if args.trace_core_vars:
        for s in systems:
            s["trace_core_vars"] = True

    return systems
