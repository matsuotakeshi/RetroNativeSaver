"""Persistent exclusion for ordinary picks, after session safety filtering.

Callers retain the input catalog for favorite matching. That catalog still
excludes current-session failures, disabled systems and invalid boot content.
"""


def load_state(api, systems, catalogs, cfg, whitelist_seed=False):
    state_path = api.resolve_app_relative_path(cfg.get('persistent_rom_blacklist_file'), 'state/persistent_rom_blacklist.json')
    state = api._load_persistent_rom_state(state_path)
    white_path = api.resolve_app_relative_path(cfg.get('persistent_rom_whitelist_file'), 'state/persistent_rom_whitelist.json')
    if whitelist_seed:
        seed = api.resolve_app_relative_path(cfg.get('persistent_rom_whitelist_seed_file'), 'persistent_rom_whitelist.default.json')
        white_state = api._load_persistent_rom_whitelist(white_path, seed)
    else:
        white_state = api._load_persistent_rom_whitelist(white_path)
    white = api._persistent_whitelisted_roms(white_state)
    if cfg.get('persistent_rom_blacklist_enabled', True):
        effective, _ = api._apply_persistent_whitelist(
            api._persistent_blacklisted_roms(state),
            white if cfg.get('persistent_rom_whitelist_enabled', True) else {})
        from fixed_rom_catalog import filtered_catalogs
        catalogs = filtered_catalogs(catalogs, {s['id']: [r for r in catalogs.get(s['id'], [])
                    if not api._rom_in_name_map(effective, s.get('name', s['id']), r.name)]
                    for s in systems})
    return state_path, state, white, catalogs
