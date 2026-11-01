"""Prepare ROMs and per-slot settings, construct cores, and apply loaded-game settings.

Order is intentional: BIOS isolation, save-path resolution/creation, Dolphin INI,
assets, then disposable memory cards. Exceptions propagate to the existing retry
handler. The caller retains preparation sequencing, DLL copying, core ownership,
initialize/load calls and cleanup; post-load settings are applied at its request.
"""
from pathlib import Path
import shutil
import zipfile


def prepare_dolphin_user_config(save_dir: Path, core_values: dict):
    """
    Create a minimal Dolphin.ini inside a frontend-provided Dolphin User dir.

    Dolphin libretro builds derive:
        User Directory = <GET_SAVE_DIRECTORY>/User

    Keeping this under the slot temp directory lets Native Saver override
    Dolphin settings without touching the user's normal RetroArch Dolphin.ini.
    """
    if not core_values:
        return None

    config_dir = save_dir / "User" / "Config"
    config_dir.mkdir(parents=True, exist_ok=True)
    ini_path = config_dir / "Dolphin.ini"

    lines = ["[Core]"]
    for key, value in core_values.items():
        lines.append(f"{key} = {value}")
    lines.append("")

    ini_path.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"[dolphin-ini] isolated config: {ini_path}",
        flush=True,
    )
    for key, value in core_values.items():
        print(
            f"[dolphin-ini] [Core] {key}={value}",
            flush=True,
        )
    return ini_path


def prepare_neocd_system(system_dir: Path, slot_dir: Path) -> Path:
    """NeoCD's shared backup RAM lives beside its BIOS, not in SAVE_DIRECTORY.

    Give each slot a firmware-only copy so both shared and per-content save
    modes stay disposable. Never fall back to the player's writable BIOS path
    if preparation fails; the existing startup retry handles the exception.
    """
    source = system_dir / "neocd"
    if not source.is_dir():
        raise FileNotFoundError(f"NeoCD BIOS directory not found: {source}")
    isolated = slot_dir / "neocd_system"
    target = isolated / "neocd"
    target.mkdir(parents=True, exist_ok=True)
    for firmware in source.rglob("*"):
        if firmware.is_file() and firmware.suffix.lower() in {".bin", ".rom", ".lo", ".zip"}:
            destination = target / firmware.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(firmware, destination)
    return isolated


def prepare_environment(system, cfg, slot_dir, slot_index, sid, resolve_path):
    """Return BIOS, save, assets and options; preserve the existing preparation order.

    sid is the caller's already-selected ID. resolve_path supplies the existing
    application-relative save-path policy without importing native_saver.
    """
    system_dir = Path(
        system.get(
            "system_dir",
            cfg.get("system_dir", r"C:\RetroArch-win64\system"),
        )
    )
    if system.get("disk_boot_mode") == "computer_two_drives":
        from computer_disks import isolated_system_dir
        system_dir = isolated_system_dir(system, system_dir, slot_dir)
    if sid == "neocd":
        system_dir = prepare_neocd_system(system_dir, slot_dir)

    save_root = resolve_path(
        cfg.get("save_dir"),
        "save",
    )
    if bool(system.get("isolated_save_dir", False)):
        save_dir = slot_dir / "save"
    elif system.get("save_dir"):
        save_dir = resolve_path(
            system.get("save_dir"),
            "save",
        )
    else:
        save_dir = save_root / sid / f"slot_{slot_index}"

    save_dir.mkdir(parents=True, exist_ok=True)

    dolphin_ini_core = system.get("dolphin_ini_core") or {}
    if dolphin_ini_core:
        prepare_dolphin_user_config(
            save_dir,
            dolphin_ini_core,
        )

    assets_dir = Path(
        system.get(
            "assets_dir",
            cfg.get("assets_dir", r"C:\RetroArch-win64\downloads"),
        )
    )

    core_options = system.get("core_options", {})
    if sid in {"dreamcast", "ps2"} and system.get("saver_memory_cards", True):
        from memory_cards import prepare as prepare_memory_cards
        system_dir, save_dir, core_options = prepare_memory_cards(system, system_dir, slot_dir)
    return system_dir, save_dir, assets_dir, core_options


def prepare_rom(system: dict, rom_path: Path, temp_root: Path) -> Path:
    """
    archive_mode:
      passthrough - leave ZIP/7z/etc. intact for the core (FBNeo etc.)
      extract     - extract one supported file from ZIP
      auto        - extract ZIP if it contains a configured content extension,
                    otherwise pass through
    """
    if system.get('_fixed_rom_catalog') and not rom_path.is_file():
        raise FileNotFoundError(f'ROM in fixed catalog is unavailable: {rom_path}; run update_rom_catalog.bat')
    if system.get("disk_boot_mode") == "pc88_two_drives":
        from pc88_disks import prepare
        return prepare(rom_path, temp_root)

    if system.get("disk_boot_mode") == "computer_two_drives":
        from computer_disks import prepare
        return prepare(system, rom_path, temp_root)

    mode = str(system.get("archive_mode", "auto")).lower()
    if rom_path.suffix.lower() != ".zip" or mode == "passthrough":
        return rom_path

    content_exts = {
        e.lower() for e in system.get("content_extensions", system.get("extensions", []))
        if e.lower() != ".zip"
    }

    try:
        with zipfile.ZipFile(rom_path, "r") as zf:
            candidates = [
                n for n in zf.namelist()
                if not n.endswith("/")
                and (not content_exts or Path(n).suffix.lower() in content_exts)
            ]

            from rom_catalog import is_msx_boot_candidate
            boot_candidates = [n for n in candidates
                               if is_msx_boot_candidate(system, Path(n))]
            if candidates and not boot_candidates:
                # Do not let auto mode pass a data-disk-only archive to the core.
                raise RuntimeError(f"No MSX boot disk (Disk 1/A) found in ZIP: {rom_path}")
            candidates = boot_candidates

            if not candidates:
                if mode == "auto":
                    return rom_path
                raise RuntimeError(f"No supported content found in ZIP: {rom_path}")

            info = max((zf.getinfo(n) for n in candidates), key=lambda x: x.file_size)
            out = temp_root / Path(info.filename).name
            with zf.open(info, "r") as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            return out

    except zipfile.BadZipFile:
        if mode == "auto":
            return rom_path
        raise


def create_configured_core(core_factory, slot_core, system_dir, save_dir, assets_dir, core_options, system):
    core = core_factory(
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
    return core


def apply_loaded_core_settings(core, system, sid):
    if '_favorite_startup_input' in system:
        from favorite_input import FavoritePress
        core._startup_input = FavoritePress(system['_favorite_startup_input'])
        core._startup_input_label = sid
    elif sid in {"megacd", "pcenginecd", "neocd"} and system.get("startup_start_twice", True):
        from startup_input import StartTwice
        core._startup_input = StartTwice()
        core._startup_input_label = sid
    if sid in {"dreamcast", "ps2"} and system.get("saver_memory_cards", True):
        from memory_cards import attach_controller
        attach_controller(core.dll, 4 if sid == "dreamcast" else 2)

    forced_aspect = float(system.get("force_aspect_ratio", 0.0) or 0.0)
    if forced_aspect > 0:
        core.display_aspect = forced_aspect


def prepare_core_paths(system, app_dir, temp_root, slot_index, attempt, failed_roms, rom_key):
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
        return None

    slot_core = temp_root / f"slot_{slot_index}_{attempt}_{source_core.name}"
    slot_dir = temp_root / f"slot_{slot_index}_{attempt}"
    slot_dir.mkdir(parents=True, exist_ok=True)
    return source_core, slot_core, slot_dir
