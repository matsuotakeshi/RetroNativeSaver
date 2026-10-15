"""Explicit handoff from the saver to a normal RetroArch game session."""
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import struct
import uuid

ENV_KEY = 'RNS_RETROARCH_REQUEST'
SIZE = 256 * 1024
HEADER = struct.Struct('<4sI')


class LaunchChannel:
    """Supervisor owns the mapping; only a normally exited worker is accepted."""
    def __init__(self):
        self.tag = 'Local\\RNSLaunch_' + uuid.uuid4().hex
        self.mapping = mmap.mmap(-1, SIZE, tagname=self.tag)
        self.reset()

    def reset(self):
        self.mapping[:HEADER.size] = HEADER.pack(b'RNSL', 0)

    def apply(self, env):
        self.reset()  # A crash/recycle must never replay an earlier request.
        env[ENV_KEY] = self.tag

    def read(self, worker_pid):
        magic, size = HEADER.unpack(self.mapping[:HEADER.size])
        if magic != b'RNSL' or not 0 <= size <= SIZE - HEADER.size:
            raise ValueError('Invalid RetroArch request header')
        if not size:
            return None
        value = json.loads(self.mapping[HEADER.size:HEADER.size+size])
        if (not isinstance(value, dict) or value.get('pid') != worker_pid
                or not isinstance(value.get('system'), dict) or not isinstance(value.get('rom'), str)):
            raise ValueError('Invalid RetroArch request owner/content')
        return value

    def close(self):
        self.mapping.close()


def resolved(value, base):
    path = Path(value)
    return (path if path.is_absolute() else Path(base) / path).resolve()


def validate_pick(system, rom, cfg, app_dir):
    if not isinstance(system, dict) or not isinstance(system.get('id'), str):
        raise ValueError('Missing system for RetroArch launch')
    core = resolved(system['core'], app_dir)
    rom = resolved(rom, app_dir)
    if not core.is_file():
        raise FileNotFoundError(f'Core not found: {core}')
    if not rom.is_file():
        raise FileNotFoundError(f'ROM not found: {rom}')
    system_dir = resolved(system.get('system_dir', cfg.get('system_dir', r'C:\RetroArch-win64\system')), app_dir)
    explicit = cfg.get('retroarch_path')
    if explicit is not None and not isinstance(explicit, str):
        raise ValueError('retroarch_path must be an executable file path')
    choices = [resolved(explicit, app_dir)] if explicit else [core.parent.parent/'retroarch.exe', system_dir.parent/'retroarch.exe']
    exe = next((p for p in choices if p.is_file()), None)
    if exe is None:
        raise FileNotFoundError('RetroArch not found; set retroarch_path in config.json')
    return dict(system=system, rom=rom, core=core, exe=exe, system_dir=system_dir)


def request_launch(system, rom, cfg, app_dir):
    validate_pick(system, rom, cfg, app_dir)
    tag = os.environ.get(ENV_KEY, '')
    if not tag.startswith('Local\\RNSLaunch_'):
        raise RuntimeError('RetroArch launch requires the saver supervisor')
    payload = json.dumps(dict(pid=os.getpid(), system=system, rom=str(resolved(rom, app_dir))), ensure_ascii=False).encode('utf-8')
    if len(payload) > SIZE - HEADER.size:
        raise ValueError('RetroArch request is too large')
    with mmap.mmap(-1, SIZE, tagname=tag) as shared:
        if shared[:4] != b'RNSL':
            raise RuntimeError('RetroArch supervisor channel is unavailable')
        shared[HEADER.size:HEADER.size+len(payload)] = payload
        shared[:HEADER.size] = HEADER.pack(b'RNSL', len(payload))


def prepare_content(pick, app_dir):
    """Keep playable disk copies across sessions, separate from saver temp data.

    Existing prepared disks are never overwritten: they can contain game saves.
    Only a newly created directory is removed if initial preparation fails.
    """
    system, source = pick['system'], pick['rom']
    multi = system.get('disk_boot_mode') in ('pc88_two_drives', 'computer_two_drives')
    extract = source.suffix.lower() == '.zip' and system.get('archive_mode', 'auto').lower() != 'passthrough'
    if not multi and not extract:
        return source, pick['system_dir'], None
    identity = json.dumps([system['id'], str(source), str(pick['core']), str(pick['system_dir']),
                           system.get('disk_boot_mode'), system.get('archive_mode'),
                           system.get('mame_machine'), system.get('mame_bios_dir'),
                           system.get('content_extensions'), system.get('extensions'),
                           system.get('pc98_copy_optional_bios')], ensure_ascii=False)
    key = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
    cache = (Path(app_dir) / 'state' / 'retroarch_content').resolve()
    folder = cache / key
    marker = folder / 'content.json'
    if marker.is_file():
        saved = json.loads(marker.read_text(encoding='utf-8'))
        content = Path(saved['content']).resolve()
        directory = Path(saved['system_dir']).resolve()
        if content != source and not content.is_relative_to(folder):
            raise ValueError('Invalid prepared RetroArch content path')
        if directory != pick['system_dir'] and not directory.is_relative_to(folder):
            raise ValueError('Invalid prepared RetroArch BIOS path')
        if not content.is_file():
            raise FileNotFoundError(f'Prepared RetroArch content is missing: {content}')
        return content, directory, folder
    folder.mkdir(parents=True, exist_ok=False)
    try:
        from startup_preparation import prepare_rom
        prepared_system = dict(system)
        # Resolve the same paths even when the launcher working directory differs.
        for name in ('rom_dir', 'mame_bios_dir'):
            if prepared_system.get(name):
                prepared_system[name] = str(resolved(prepared_system[name], app_dir))
        content = prepare_rom(prepared_system, source, folder)
        directory = pick['system_dir']
        if system.get('disk_boot_mode') == 'computer_two_drives':
            from computer_disks import isolated_system_dir
            directory = isolated_system_dir(system, directory, folder)
        if multi:
            # Generic boot.cmd/drive1 names would collide in RetroArch's saves.
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', source.stem)[:100]
            named = folder / f'{stem}_{key[:8]}{content.suffix}'
            content.rename(named)
            content = named
        marker.write_text(json.dumps(dict(content=str(content.resolve()), system_dir=str(directory.resolve())),
                                     ensure_ascii=False, indent=2), encoding='utf-8')
        return content, directory, folder
    except BaseException:
        if folder.resolve().parent == cache and folder.name == key:
            shutil.rmtree(folder, ignore_errors=True)
        raise


def config_value(value):
    value = str(value).replace('\\', '/')
    if any(c in value for c in ('"', '\r', '\n', '\x00')):
        raise ValueError('Invalid path for RetroArch configuration')
    return '"' + value + '"'


def launch(value, cfg, app_dir):
    pick = validate_pick(value['system'], value['rom'], cfg, app_dir)
    content, directory, folder = prepare_content(pick, app_dir)
    # A session-specific append file avoids changing the user's retroarch.cfg.
    root = Path(app_dir) / 'state' / 'retroarch_launch'
    root.mkdir(parents=True, exist_ok=True)
    append = root / (uuid.uuid4().hex + '.cfg')
    append.write_text('system_directory = ' + config_value(directory) + '\nconfig_save_on_exit = "false"\n', encoding='utf-8')
    cmd = [str(pick['exe']), '-L', str(pick['core']), '--appendconfig', str(append), str(content)]
    from desktop_launch import start_process
    try:
        pid = start_process(cmd, pick['exe'].parent)
    except BaseException:
        append.unlink(missing_ok=True)
        raise
    # RetroArch may re-read append config during a game; leave this tiny file.
    print(f'[retroarch] launched pid={pid} system={pick["system"]["id"]} rom={pick["rom"]} content={content}', flush=True)
    return pid
