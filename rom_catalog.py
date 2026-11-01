"""ROM catalog scanning without frontend or emulator initialization.

Enumeration order, progress cadence, optional ZIP validation and each computer
family's existing boot-candidate rules are preserved. ROM extraction stays in
the launch path, including deferred ZIP validation for computer_two_drives.
"""
from pathlib import Path
import zipfile
from startup_timing import span
from title_metadata import _title_key


def is_msx_boot_candidate(system: dict, path: Path) -> bool:
    """Keep unnumbered content; only Disk 1/A starts a numbered MSX disk set.

    Share the existing computer disk-label parser, including the priority of
    "Disk 1 of N" over secondary labels. Never infer dump quality from [a].
    ZIP members are checked again when extracted; no archive reads are needed
    when loading an existing fixed catalog.
    """
    if system.get("id") != "msx" or path.suffix.lower() not in {".dsk", ".zip"}:
        return True
    from computer_disks import identity
    disk = identity(path)
    return disk is None or disk[1] == 1


def should_exclude_rom(system: dict, path: Path) -> bool:
    if not is_msx_boot_candidate(system, path):
        return True
    name = path.name.lower()

    # Global safety defaults: BIOS/boot ROM dumps should not be launched as games.
    default_tokens = [
        "[bios]",
        "(bios)",
        "boot rom",
        "bootrom",
    ]

    configured = [
        str(x).lower()
        for x in system.get("exclude_name_contains", [])
    ]

    for token in default_tokens + configured:
        if token and token in name:
            return True

    return False


def _report_empty_catalog(system, rom_dir, recursive, extensions):
    # Helpful diagnostic for systems whose ROMs are stored in an archive
    # extension that is missing from the configured catalog list.
    try:
        probe = rom_dir.rglob("*") if recursive else rom_dir.iterdir()
        ext_counts = {}
        for p in probe:
            if not p.is_file():
                continue
            ext = p.suffix.lower() or "<no-extension>"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

        if ext_counts:
            summary = ", ".join(
                f"{ext}={count}"
                for ext, count in sorted(
                    ext_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:12]
            )
            print(
                f"[catalog] [{system['name']}] detected file extensions: "
                f"{summary}",
                flush=True,
            )
            print(
                f"[catalog] [{system['name']}] configured extensions: "
                f"{', '.join(sorted(extensions)) if extensions else '<all>'}",
                flush=True,
            )
    except Exception as exc:
        print(
            f"[catalog] [{system['name']}] extension diagnostic warning: {exc}",
            flush=True,
        )


def scan_roms(system: dict, progress=None):
    rom_dir = Path(system["rom_dir"])
    if not rom_dir.exists():
        print(f"[catalog] SKIP [{system['name']}] directory not found: {rom_dir}")
        return []

    extensions = {e.lower() for e in system.get("extensions", [])}
    recursive = bool(system.get("recursive", False))
    iterator = rom_dir.rglob("*") if recursive else rom_dir.iterdir()

    validate_archives = bool(system.get("validate_archive_contents", False))
    # Computer collections can contain thousands of large ZIPs. Opening all
    # of them before creating any tile leaves only the black backdrop visible.
    # Validate/extract only the selected archive in computer_disks.prepare().
    if system.get("disk_boot_mode") == "computer_two_drives":
        validate_archives = False
        print(f"[catalog] [{system['name']}] scanning filenames; ZIP validation deferred until launch", flush=True)
    archive_mode = str(system.get("archive_mode", "auto")).lower()
    content_exts = {
        str(e).lower()
        for e in system.get(
            "content_extensions",
            system.get("extensions", []),
        )
        if str(e).lower() != ".zip"
    }

    roms = []
    from catalog_paths import CatalogPaths
    path_info = CatalogPaths()
    excluded = 0
    invalid_archives = 0

    for scanned, p in enumerate(iterator, 1):
        if progress and scanned % 128 == 0:
            progress(scanned)
        if not path_info.is_file(p):
            continue
        if extensions and p.suffix.lower() not in extensions:
            continue
        if should_exclude_rom(system, p):
            excluded += 1
            continue

        # Optional catalog-time archive validation. This is useful when a ROM
        # directory contains ZIPs belonging to adjacent platforms. Without
        # this check they look valid by outer extension and fail only after a
        # slot has already been selected.
        if (
            validate_archives
            and p.suffix.lower() == ".zip"
            and archive_mode == "extract"
            and content_exts
        ):
            try:
                with zipfile.ZipFile(p, "r") as zf:
                    has_supported_content = any(
                        not info.is_dir()
                        and Path(info.filename).suffix.lower() in content_exts
                        and is_msx_boot_candidate(system, Path(info.filename))
                        for info in zf.infolist()
                    )
                if not has_supported_content:
                    invalid_archives += 1
                    continue
            except (zipfile.BadZipFile, OSError):
                invalid_archives += 1
                continue

        roms.append(p)

    if system.get("disk_boot_mode") == "computer_two_drives":
        from computer_disks import candidates
        roms = candidates(roms)

    if system.get("disk_boot_mode") == "pc88_two_drives":
        from pc88_disks import boot_candidates
        before = len(roms)
        with span("pc88_boot_candidates", input_count=before):
            roms = boot_candidates(roms)
        print(f"[pc88] boot candidates={len(roms)}; secondary/user disks omitted={before - len(roms)}", flush=True)

    details = []
    if excluded:
        details.append(f"{excluded} excluded")
    if invalid_archives:
        details.append(f"{invalid_archives} invalid archive(s)")

    if details:
        print(
            f"[catalog] [{system['name']}] {len(roms)} ROM(s) "
            f"({', '.join(details)})"
        )
    else:
        print(f"[catalog] [{system['name']}] {len(roms)} ROM(s)")

    if not roms:
        _report_empty_catalog(system, rom_dir, recursive, extensions)

    return roms


def build_catalogs(systems, title_maps, worker_mode, session_quarantine, write_runtime_trace,
                   catalog_path=None):
    from fixed_rom_catalog import Catalogs, read_catalog, cached_roms
    catalogs = Catalogs()
    with span('fixed_catalog_load'):
        saved = read_catalog(catalog_path)
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
        with span("rom_scan", system=sid):
            roms = cached_roms(system, saved, catalogs)
            if roms is None:
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
