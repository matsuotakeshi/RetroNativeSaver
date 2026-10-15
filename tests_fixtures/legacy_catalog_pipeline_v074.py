"""v0.20.74 main catalog loop, unmodified apart from the function boundary."""

def build_catalogs(systems, title_maps, worker_mode, session_quarantine, write_runtime_trace):
    catalogs = {}
    for system in systems:
        if not bool(system.get("enabled", True)):
            print(f"[config] DISABLED [{system.get('name', system.get('id', '?'))}]")
            continue

        backend = str(system.get("render_backend", "software")).lower()
        if backend not in ("software", "opengl", "glcore"):
            print(
                f"[config] SKIP [{system.get('name', system.get('id', '?'))}] "
                f"render_backend={backend} (unsupported frontend backend)"
            )
            continue

        sid = system["id"]
        write_runtime_trace("ROM_CATALOG", system=system.get("name", sid))
        print(f"[prepare] scanning [{sid}]", flush=True)
        roms = scan_roms(system, progress=lambda count: write_runtime_trace(
            "ROM_CATALOG", system=system.get("name", sid), call_count=count))

        if worker_mode and roms:
            system_name = str(
                system.get("name", system.get("id", "?"))
            )
            quarantined_names = session_quarantine.get(
                system_name,
                set(),
            )
            if quarantined_names:
                before = len(roms)
                roms = [
                    rom for rom in roms
                    if rom.name.casefold() not in quarantined_names
                ]
                removed = before - len(roms)
                if removed:
                    print(
                        f"[session-safety] [{system_name}] "
                        f"quarantine filtered {removed} ROM(s); "
                        f"{len(roms)} remain",
                        flush=True,
                    )

        # Optional safety filter: only keep ROMs whose shortname exists in the
        # loaded title DB. This is useful for MAME Current when a ROM directory
        # contains sets from a different MAME generation.
        if bool(system.get("require_title_db_match", False)):
            title_map = title_maps.get(sid, {})
            if title_map:
                before = len(roms)
                roms = [
                    rom for rom in roms
                    if _title_key(rom) in title_map
                ]
                removed = before - len(roms)
                print(
                    f"[catalog] [{system.get('name', sid)}] "
                    f"title-db filter kept {len(roms)}/{before} ROM(s)"
                    + (f" ({removed} removed)" if removed else ""),
                    flush=True,
                )
            else:
                print(
                    f"[catalog] [{system.get('name', sid)}] "
                    f"title-db filter skipped: title DB is empty or unavailable",
                    flush=True,
                )

        if roms:
            catalogs[sid] = roms

    return catalogs
