from pathlib import Path

from title_metadata import resolve_display_title

def prepare_core_paths(system, app_dir, temp_root, slot_index, attempt, failed_roms, rom_key):
    for _ in range(1):
        source_core = Path(system["core"])
        if not source_core.is_absolute():
            source_core = app_dir / source_core
        source_core = source_core.resolve()
        if not source_core.exists():
            print(
                f"[slot {slot_index + 1}] START FAILED "
                f"[{system['name']}] core not found: {source_core}"
            )
            failed_roms.add(rom_key)
            continue

        slot_core = temp_root / f"slot_{slot_index}_{attempt}_{source_core.name}"
        slot_dir = temp_root / f"slot_{slot_index}_{attempt}"
        slot_dir.mkdir(parents=True, exist_ok=True)
        return source_core, slot_core, slot_dir
    return None


def append_slot_metadata(actual_system, actual_rom, title_maps, slot_overlays, slot_runtime_contexts):
    display_title = resolve_display_title(
        actual_system,
        actual_rom,
        title_maps,
    )
    slot_overlays.append((
        actual_system.get("name", actual_system.get("id", "")),
        display_title,
    ))
    slot_runtime_contexts.append((
        actual_system.get("name", actual_system.get("id", "")),
        actual_rom.name,
    ))


def record_favorite_startup(initial_system, system, rom, favorite_retries, cycle_group_usage):
    from resource_policy import replace_cycle_usage
    replace_cycle_usage(initial_system, system, cycle_group_usage)
    favorite_keys = {(x['id'], str(r)) for x, r in favorite_retries}
    status = 'READY' if (system['id'], str(rom)) in favorite_keys else 'normal fallback'
    print(f"[favorites] {status}: [{system['id']}] {rom.name}", flush=True)
