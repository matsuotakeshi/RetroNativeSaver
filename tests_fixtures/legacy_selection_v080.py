import random
from resource_policy import (_resource_group_can_add, _resource_group_add_usage, _resource_group_limit)
import json

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

def initial_retry_candidates(initial_system, initial_rom, systems, catalogs, failed_roms, favorite_retries):
    candidates = [(initial_system, initial_rom)]
    if favorite_retries:
        alternatives = [pair for pair in favorite_retries
                        if (pair[0]['id'], str(pair[1])) != (initial_system['id'], str(initial_rom))
                        and str(pair[1]) not in failed_roms]
        random.shuffle(alternatives)
        candidates.extend(alternatives)
    favorite_fallback_logged = False
    preferred_system = initial_system

    enabled_supported = [
        s for s in systems
        if bool(s.get("enabled", True))
        and str(s.get("render_backend", "software")).lower() in ("software", "opengl", "glcore")
        and s.get("id") in catalogs
        and catalogs[s["id"]]
    ]
    return candidates, enabled_supported


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
