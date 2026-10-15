"""Unmodified v0.20.73 ROM preparation; tests only."""
from pathlib import Path
import zipfile
import shutil

def prepare_rom(system: dict, rom_path: Path, temp_root: Path) -> Path:
    """
    archive_mode:
      passthrough - leave ZIP/7z/etc. intact for the core (FBNeo etc.)
      extract     - extract one supported file from ZIP
      auto        - extract ZIP if it contains a configured content extension,
                    otherwise pass through
    """
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
