"""Resource accounting from system/config dictionaries; no emulator imports.

Cycle and independent modes use the normal-cycle group coercion and fallback
policy. No group (including heavy_cd) is special.
"""


def _resource_weight(system):
    """Shared weight conversion; callers preserve their own error/skip policy."""
    return max(0, int(system.get('resource_weight', 1)))

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
        weight = _resource_weight(system)
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
        _resource_group_remove_usage(replacing_system, usage)

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

def _resource_group_remove_usage(system, usage):
    group, weight = _resource_group_info(system)
    if group:
        usage[group] = max(0, usage.get(group, 0) - weight)


def replace_cycle_usage(old_system, new_system, usage):
    """Commit a successful retry to the existing mutable cycle reservation."""
    _resource_group_remove_usage(old_system, usage)
    _resource_group_add_usage(new_system, usage)


def independent_usage(occupied):
    counts, usage = {}, {}
    for system, rom in occupied:
        sid = system['id']
        counts[sid] = counts.get(sid, 0) + 1
        _resource_group_add_usage(system, usage)
    return counts, usage


def independent_can_add(system, counts, usage, cfg):
    if counts.get(system['id'], 0) >= int(system.get('max_concurrent', 999)):
        return False
    return _resource_group_can_add(system, usage, cfg)


def independent_fits(system, picks, cfg):
    """Use the same group interpretation for favorite reservations and selection."""
    sid = system['id']
    if sum(s['id'] == sid for s, _ in picks) >= int(system.get('max_concurrent', 999)):
        return False
    return _resource_group_can_add(system, _resource_group_usage_from_picks(picks), cfg)
