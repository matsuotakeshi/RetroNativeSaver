"""Prepare isolated two-drive content for PC-98, X1 and X68000."""
from pathlib import Path
import re
import shutil
import zipfile

FORMATS = {
    'fm7': {'.d77', '.d88', '.dsk', '.imd', '.td0', '.mfi', '.mfm', '.hfe'},
    'pc98': {'.d88', '.88d', '.d98', '.98d', '.fdi', '.fdd', '.hdm', '.dup', '.2hd', '.xdf', '.nfd', '.hdi', '.nhd', '.thd'},
    'x1': {'.d88', '.88d', '.2d', '.2hd', '.tfd', '.hdm', '.xdf', '.dup', '.dx1'},
    'x68000': {'.dim', '.img', '.d88', '.88d', '.hdm', '.dup', '.2hd', '.xdf', '.hdf'},
}
HARD = {'.hdi', '.nhd', '.thd', '.hdf'}
LABEL = re.compile(r'(?i)(?<!\w)(?:disk|disc)[ _-]*([0-9]+|[a-z])(?!\w)(?:\s+of\s+(\d+))?')
# Only recognized disk-role notes may differ within an explicitly numbered set.
# Keep revision, language, dump and unknown annotations in the matching key.
DISK_ROLE_NOTE = re.compile(
    r'(?i)\(\s*(?:(?:disk|disc)[ _-]*(?:[0-9]+|[a-z])|system|boot|program|data|user)\s*\)'
)


def unique_images(paths):
    # Archives often contain the same dump in both NFD and D88 formats.
    priority = {'.nfd': 0, '.fdi': 1, '.d88': 2, '.hdm': 3}
    result = {}
    for path in sorted(paths, key=lambda p: (priority.get(p.suffix.lower(), 10), str(p).casefold())):
        result.setdefault(str(path.with_suffix('')).casefold(), path)
    return list(result.values())


def identity(path):
    matches = list(LABEL.finditer(path.stem))
    if not matches:
        return None
    numbered = next((m for m in matches if m.group(2) and m.group(1).isdigit()), None)
    match = numbered or matches[-1]
    value = match.group(1).lower()
    index = int(value) if value.isdigit() else ord(value) - 96
    if numbered:
        # "Disk 2 of 5 (Disk 1)" is the second disk, not the boot disk.
        # Match its System disk while keeping the total and edition metadata.
        suffix = DISK_ROLE_NOTE.sub('', path.stem[match.end():])
        key = path.stem[:match.start()] + f'<disk of {int(match.group(2))}>' + suffix
        return LABEL.sub('<disk>', key).strip().casefold(), index
    # Keep the existing matching rules for simple Disk 1/2 and Disk A/B names.
    return LABEL.sub('<disk>', path.stem).casefold(), index


def candidates(paths):
    return [p for p in paths if p.suffix.lower() == '.zip' or
            ((identity(p) is None or identity(p)[1] == 1) and
             not re.search(r'(?i)\b(user|data)\s*disk\b', p.stem))]


def select(path, members):
    info = identity(path)
    if info is None or path.suffix.lower() in HARD:
        return [path]
    selected = []
    for index in (1, 2):
        hits = [p for p in members if p.parent == path.parent and identity(p) == (info[0], index)]
        if len(hits) > 1:
            raise ValueError(f'Ambiguous disk {index}: {hits}')
        if not hits and index == 1:
            raise ValueError(f'Disk 1/A missing: {path}')
        selected.extend(hits)
    return selected


def archive_images(source, formats):
    """Read names only; extraction always uses fixed slot-local filenames."""
    with zipfile.ZipFile(source) as archive:
        members = [Path(i.filename) for i in archive.infolist()
                   if not i.is_dir() and Path(i.filename).suffix.lower() in formats]
    if len(members) != len(set(members)):
        raise ValueError(f'Duplicate ZIP member: {source}')
    members = unique_images(members)
    primary = [p for p in members if not any(part.casefold() in ('alts', 'extras') for part in p.parts[:-1])]
    return primary or members


def zip_disks(source, formats, sid):
    """Pair explicitly labeled sibling ZIPs, never mix titles or revisions."""
    outer = identity(source)
    members = archive_images(source, formats)
    starts = candidates(members)
    # Older fixed catalogs/favorites may contain a separately zipped Disk B.
    # Resolve its matching boot archive rather than mounting B in drive 1.
    if not starts and outer and outer[1] > 1:
        siblings = [p for p in source.parent.iterdir() if p.is_file() and p.suffix.lower() == '.zip']
        boots = [p for p in siblings if identity(p) == (outer[0], 1)]
        if len(boots) != 1:
            raise ValueError(f'[{sid}] Missing or ambiguous Disk 1/A ZIP: {source}')
        source = boots[0]
        outer = identity(source)
        members = archive_images(source, formats)
        starts = candidates(members)
    if len(starts) != 1:
        raise ValueError(f'[{sid}] ZIP must contain one unambiguous boot set; found {len(starts)}: {source}')
    selected = select(starts[0], members)
    result = [(source, member) for member in selected]
    boot = identity(selected[0])
    # An in-archive pair takes precedence. Unlabeled disks/HDDs stay standalone.
    if len(selected) != 1 or not outer or outer[1] != 1 or not boot or selected[0].suffix.lower() in HARD:
        return result
    siblings = [p for p in source.parent.iterdir() if p.is_file() and p.suffix.lower() == '.zip'
                and identity(p) == (outer[0], 2)]
    if len(siblings) > 1:
        raise ValueError(f'[{sid}] Ambiguous Disk 2/B ZIP: {siblings}')
    if siblings:
        companion = siblings[0]
        matches = [p for p in archive_images(companion, formats) if identity(p) == (boot[0], 2)]
        if len(matches) != 1:
            raise ValueError(f'[{sid}] Missing or ambiguous matching Disk 2/B image: {companion}')
        result.append((companion, matches[0]))
    return result


def prepare(system, source, destination):
    sid = system['id']
    formats = FORMATS[sid]
    destination.mkdir(parents=True, exist_ok=True)
    selected = []
    if source.suffix.lower() == '.zip':
        paths = []
        for index, (archive_path, member) in enumerate(zip_disks(source, formats, sid), 1):
            output = destination / f'drive{index}{member.suffix.lower()}'
            # Never extract archive paths: fixed local names prevent traversal.
            with zipfile.ZipFile(archive_path) as archive:
                with archive.open(member.as_posix()) as src, output.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
            paths.append(output)
            print(f'[{sid}] drive{index}={archive_path}!{member}', flush=True)
    else:
        members = [p for p in source.parent.iterdir() if p.is_file() and p.suffix.lower() in formats]
        selected = select(source, members)
        paths = []
        for index, member in enumerate(selected, 1):
            output = destination / f'drive{index}{member.suffix.lower()}'
            shutil.copyfile(member, output)
            paths.append(output)
            print(f'[{sid}] drive{index}={member}', flush=True)
    if len(paths) == 1:
        print(f'[{sid}] drive2=<empty>', flush=True)
    if paths[0].suffix.lower() in HARD:
        return paths[0]
    if sid == 'fm7':
        from fm7_disks import command_file
        return command_file(system, source, paths, destination)
    if sid == 'pc98':
        result = destination / 'boot.cmd'
        result.write_text('np2kai ' + ' '.join('"' + str(p.resolve()) + '"' for p in paths) + '\n', encoding='utf-8')
    else:
        result = destination / 'boot.m3u'
        result.write_text(''.join(p.resolve().as_posix() + '\n' for p in paths), encoding='utf-8')
    return result


def isolated_system_dir(system, directory, destination):
    if system['id'] == 'fm7':
        return destination / 'system'
    subdir = {'pc98': 'np2kai', 'x1': 'xmil', 'x68000': 'keropi'}[system['id']]
    target = destination / 'system' / subdir
    target.mkdir(parents=True, exist_ok=True)
    # Copy firmware only. Core-generated configs/SRAM stay in this slot.
    for source in (directory / subdir).iterdir():
        if system['id'] == 'pc98' and not system.get('pc98_copy_optional_bios', False) and source.name.lower() in ('d8000.rom', 'bios9821.rom'):
            continue
        if source.is_file() and source.suffix.lower() in {'.rom', '.bmp', '.wav', '.dat', '.x1', '.x1t'} and source.name.lower() != 'sram.dat':
            shutil.copyfile(source, target / source.name)
    return target.parent
