"""Frozen v0.20.72 catalog functions; tests only."""
from pathlib import Path
import zipfile

def should_exclude_rom(system: dict, path: Path) -> bool:
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
    excluded = 0
    invalid_archives = 0

    for scanned, p in enumerate(iterator, 1):
        if progress and scanned % 128 == 0:
            progress(scanned)
        if not p.is_file():
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

    return roms
