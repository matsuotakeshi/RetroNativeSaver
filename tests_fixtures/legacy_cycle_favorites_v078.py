"""Original main blocks from v0.20.78, test only."""
from favorites import load_favorites, favorite_candidates
from resource_policy import _resource_group_usage_from_picks, _resource_group_can_add

def load_cycle_favorites(favorites_path, systems, catalogs, failed_roms):
    try:
        favorite_settings = load_favorites(favorites_path)
        eligible_systems = [x for x in systems if x.get('enabled', True)
                            and str(x.get('render_backend', 'software')).lower()
                            in ('software', 'opengl', 'glcore')]
        favorites = [pair for pair in favorite_candidates(eligible_systems, catalogs, favorite_settings)
                     if str(pair[1]) not in failed_roms]
        if favorite_settings.get('enabled', True) and favorite_settings['items'] and not favorites:
            print("[favorites] no available favorites; using normal selection", flush=True)
    except (OSError, ValueError) as exc:
        favorites = []
        print(f"[favorites] configuration error; using normal selection: {exc}", flush=True)
    return favorites


def cycle_favorite_retries(i, system, rom, favorites, picks, slot_count, cfg):
    favorite_retries = None
    if i == 0 and any(x['id'] == system['id'] and r == rom for x, r in favorites):
        other_picks = picks[1:]
        other_usage = _resource_group_usage_from_picks(other_picks)
        favorite_retries = [
            (x, r) for x, r in favorites
            if sum(1 for other, _ in other_picks if other['id'] == x['id'])
               < int(x.get('max_concurrent', slot_count))
            and _resource_group_can_add(x, other_usage, cfg)
            and ((x['id'] == system['id'] and r == rom)
                 or not any(other['id'] == x['id'] and other_rom == r
                            for other, other_rom in other_picks))
        ]
    return favorite_retries
