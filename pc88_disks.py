"""PC-88 boot selection and two-drive playlists for QUASI88."""
from pathlib import Path
import re
import shutil

DISK_EXTENSIONS = {'.d88', '.88d', '.u88'}
# Require an explicit Disk/Disc label, not a number in the game title.
LABEL = re.compile(r'(?i)(?<!\w)(?:disk|disc)[ _-]*([0-9]+|[a-z])(?!\w)')
NON_BOOT = re.compile(r'(?i)\b(?:user|data)\s*disk\b')


def identity(path):
    matches = list(LABEL.finditer(path.stem))
    if not matches:
        return None
    match = matches[-1]
    value = match.group(1).lower()
    index = int(value) if value.isdigit() else ord(value) - ord('a') + 1
    family = 'number' if value.isdigit() else 'letter'
    key = (path.stem[:match.start()] + '<disk>' + path.stem[match.end():]).casefold()
    return key, family, index


def playlist_disks(path):
    disks = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        disk = Path(line)
        if not disk.is_absolute():
            disk = path.parent / disk
        if disk.suffix.lower() not in DISK_EXTENSIONS or not disk.is_file():
            raise ValueError(f'PC88 playlist disk missing or unsupported: {disk}')
        disks.append(disk)
    if not disks:
        raise ValueError(f'PC88 playlist is empty: {path}')
    return disks


def boot_candidates(paths):
    referenced = set()
    invalid = set()
    for path in paths:
        if path.suffix.lower() == '.m3u':
            try:
                referenced.update(p.resolve() for p in playlist_disks(path))
            except (OSError, ValueError) as exc:
                invalid.add(path)
                print(f'[pc88] invalid playlist: {exc}', flush=True)
    result = []
    for path in paths:
        if path in invalid or (referenced and path.resolve() in referenced):
            continue
        info = identity(path)
        if info is not None and info[2] != 1:
            continue
        if NON_BOOT.search(path.stem):
            continue
        result.append(path)
    return result


def select_disks(path):
    if path.suffix.lower() == '.m3u':
        return playlist_disks(path)[:2]
    info = identity(path)
    if info is None:
        return [path]
    key, family, _ = info
    members = {}
    for candidate in path.parent.iterdir():
        if not candidate.is_file() or candidate.suffix.lower() not in DISK_EXTENSIONS:
            continue
        other = identity(candidate)
        if other and other[:2] == (key, family):
            members.setdefault(other[2], []).append(candidate)
    if 1 not in members:
        raise ValueError(f'PC88 Disk 1/A not found: {path}')
    selected = []
    for index in (1, 2):
        matches = members.get(index, [])
        if len(matches) > 1:
            raise ValueError(f'PC88 ambiguous disk {index}: {matches}')
        selected.extend(matches)
    return selected


def prepare(path, temp_root):
    disks = select_disks(path)
    temp_root.mkdir(parents=True, exist_ok=True)
    # Copies isolate original images from native core writes and avoid playlist
    # encoding/path length issues for the original content filenames.
    names = []
    for index, disk in enumerate(disks, 1):
        name = f'pc88_drive{index}.d88'
        shutil.copyfile(disk, temp_root / name)
        names.append(name)
        print(f'[pc88] drive{index}={disk}', flush=True)
    if len(disks) == 1:
        print('[pc88] drive2=<empty>', flush=True)
    playlist = temp_root / 'pc88_boot.m3u'
    playlist.write_text('\n'.join(names) + '\n', encoding='utf-8')
    return playlist
