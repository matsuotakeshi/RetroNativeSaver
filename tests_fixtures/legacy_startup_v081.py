def resolve_app_relative_path(value, default_name):
    """
    Resolve config paths that belong to Retro Native Saver itself.

    Windows launches .scr files with a working directory that is not guaranteed
    to be the application's install directory (commonly System32 after reboot).
    Therefore writable relative paths such as "save" must be anchored to
    APP_DIR, not to os.getcwd().
    """
    raw = value
    if raw is None or str(raw).strip() == "":
        raw = default_name

    path = Path(raw)
    if not path.is_absolute():
        path = APP_DIR / path
    return path.resolve()

def prepare_dolphin_user_config(save_dir: Path, core_values: dict):
    from startup_preparation import prepare_dolphin_user_config as prepare
    return prepare(save_dir, core_values)

def start_slot_with_retry(slot_index, initial_system, initial_rom,
                          systems, catalogs, cfg, temp_root,
                          failed_roms, max_attempts=5, worker_mode=False,
                          cycle_number=0, cycle_group_usage=None, favorite_retries=None):
    """
    Start one slot. If a selected ROM/core fails to load, mark that ROM as failed
    for this run and retry with another candidate. The whole saver continues.
    """
    from slot_selection import initial_retry_candidates
    candidates, enabled_supported = initial_retry_candidates(initial_system, initial_rom, systems, catalogs, failed_roms, favorite_retries)
    favorite_fallback_logged = False
    preferred_system = initial_system

    attempt = 0
    while attempt < max_attempts:
        attempt += 1

        if candidates:
            system, rom = candidates.pop(0)
        else:
            if favorite_retries is not None and not favorite_fallback_logged:
                print("[favorites] favorite startup candidates exhausted; trying normal ROMs", flush=True)
                favorite_fallback_logged = True
            if not enabled_supported:
                raise RuntimeError("No supported systems available for retry.")

            # Prefer replacing a failed title with another title from the same
            # system. This preserves the selector's max_concurrent balance.
            system = preferred_system
            sid = system["id"]
            pool = [
                r for r in catalogs.get(sid, [])
                if str(r) not in failed_roms
            ]

            # Only fall back to another system if the preferred system has no
            # usable candidates left.
            if not pool:
                fallback_systems = [
                    s for s in enabled_supported
                    if any(
                        str(r) not in failed_roms
                        for r in catalogs.get(s["id"], [])
                    )
                    and _resource_group_can_add(
                        s,
                        cycle_group_usage or {},
                        cfg,
                        replacing_system=preferred_system,
                    )
                ]
                if not fallback_systems:
                    continue
                system = random.choice(fallback_systems)
                sid = system["id"]
                pool = [
                    r for r in catalogs[sid]
                    if str(r) not in failed_roms
                ]

            rom = random.choice(pool)

        sid = system["id"]
        rom_key = str(rom)

        if rom_key in failed_roms:
            continue

        source_core = Path(system["core"])
        if not source_core.is_absolute():
            source_core = APP_DIR / source_core
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

        core = None
        try:
            write_runtime_trace(
                "START_ENTER",
                cycle=cycle_number,
                slot=slot_index + 1,
                system=system.get("name", sid),
                rom=rom.name,
            )

            shutil.copy2(source_core, slot_core)
            actual_rom = prepare_rom(system, rom, slot_dir)

            from startup_preparation import prepare_environment
            system_dir, save_dir, assets_dir, core_options = prepare_environment(
                system, cfg, slot_dir, slot_index, sid, resolve_app_relative_path,
            )

            core = LibretroCore(
                slot_core,
                system_dir,
                save_dir,
                assets_dir=assets_dir,
                core_options=core_options,
                render_backend=system.get("render_backend", "software"),
                hw_context_width=int(system.get("hw_context_width", 640)),
                hw_context_height=int(system.get("hw_context_height", 480)),
                hw_readback=bool(system.get("hw_readback", True)),
                env_trace_frames=int(system.get("env_trace_frames", 0)),
                provide_log_interface=bool(system.get("provide_log_interface", True)),
                provide_perf_interface=bool(system.get("provide_perf_interface", True)),
                frame_rebind_context=bool(system.get("frame_rebind_context", True)),
                trace_core_vars=bool(system.get("trace_core_vars", False)),
                destroy_hw_before_unload=bool(
                    system.get("destroy_hw_before_unload", False)
                ),
            )
            core.initialize()
            av = core.load_game(actual_rom)
            if sid in {"megacd", "pcenginecd"} and system.get("startup_start_twice", True):
                from startup_input import StartTwice
                core._startup_input = StartTwice()
                core._startup_input_label = sid
            if sid in {"dreamcast", "ps2"} and system.get("saver_memory_cards", True):
                from memory_cards import attach_controller
                attach_controller(core.dll, 4 if sid == "dreamcast" else 2)

            forced_aspect = float(system.get("force_aspect_ratio", 0.0) or 0.0)
            if forced_aspect > 0:
                core.display_aspect = forced_aspect

            write_runtime_trace(
                "START_RETURN",
                cycle=cycle_number,
                slot=slot_index + 1,
                system=system.get("name", sid),
                rom=rom.name,
            )

            print(
                f"[slot {slot_index + 1}] READY "
                f"[{system['name']}] {rom.name}"
            )
            if favorite_retries is not None and cycle_group_usage is not None:
                from resource_policy import replace_cycle_usage
                replace_cycle_usage(initial_system, system, cycle_group_usage)
                favorite_keys = {(x['id'], str(r)) for x, r in favorite_retries}
                status = 'READY' if (system['id'], str(rom)) in favorite_keys else 'normal fallback'
                print(f"[favorites] {status}: [{system['id']}] {rom.name}", flush=True)
            return core, av, system, rom

        except Exception as exc:
            startup_phase = (
                "START_NATIVE_FAULT"
                if is_native_access_violation(exc)
                else "START_FAILED"
            )
            write_runtime_trace(
                startup_phase,
                cycle=cycle_number,
                slot=slot_index + 1,
                system=system.get("name", sid),
                rom=rom.name,
            )

            print(
                f"[slot {slot_index + 1}] START FAILED "
                f"[{system['name']}] {rom.name}: {exc}"
            )
            failed_roms.add(rom_key)

            if core is not None:
                if bool(system.get("process_recycle_required", False)):
                    print(
                        "[shutdown] process-isolated core failed during startup; "
                        "skipping unsafe in-process close",
                        flush=True,
                    )
                    if worker_mode:
                        print(
                            "[worker] startup failure in process-isolated core; "
                            "terminating worker cleanly",
                            flush=True,
                        )
                        hard_exit_process(WORKER_RESTART_EXIT_CODE)
                else:
                    try:
                        core.close()
                    except Exception:
                        pass

    raise RuntimeError(
        f"slot {slot_index + 1}: failed to start a game after {max_attempts} attempts"
    )
