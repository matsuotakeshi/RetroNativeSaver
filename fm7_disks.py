"""Isolated MAME Current floppy boot, never execute CMD through a shell."""
from pathlib import Path
import re
import shutil


def machine_for(system, source):
    machine = system.get('mame_machine', 'auto')
    if machine == 'auto':
        machine = 'fm77av' if re.search(r'(?i)fm[ _-]*77[ _-]*av', str(source)) else 'fm7'
    if machine not in ('fm7', 'fm77av'):
        raise ValueError(f'Unsupported FM-7 machine: {machine}')
    return machine


def quote(path):
    value = Path(path).resolve().as_posix()
    if any(c in value for c in ('"', '\n', '\r')):
        raise ValueError('Invalid path for MAME command file')
    return '"' + value + '"'


def command_file(system, source, disks, destination):
    machine = machine_for(system, source)
    bios = Path(system.get('mame_bios_dir', system['rom_dir']))
    target = destination / 'system' / 'mame' / 'roms'
    target.mkdir(parents=True, exist_ok=True)
    for name in (['fm7.zip'] if machine == 'fm7' else ['fm7.zip', 'fm77av.zip']):
        source_bios = bios / name
        if not source_bios.is_file():
            raise FileNotFoundError(f'FM-7 BIOS not found: {source_bios}')
        shutil.copyfile(source_bios, target / name)
    args = [machine, '-rompath', quote(target), '-noreadconfig', '-nowriteconfig', '-skip_gameinfo']
    # Explicitly keep mutable MAME state in the temporary slot directory.
    for option, folder in [('cfg_directory', 'cfg'), ('nvram_directory', 'nvram'),
                           ('diff_directory', 'diff'), ('state_directory', 'sta')]:
        path = destination / folder
        path.mkdir(exist_ok=True)
        args.extend(['-' + option, quote(path)])
    for index, disk in enumerate(disks, 1):
        args.extend([f'-flop{index}', quote(disk)])
    result = destination / 'boot.cmd'
    result.write_text(' '.join(args) + '\n', encoding='utf-8')
    print(f'[fm7] MAME machine={machine}; isolated BIOS and floppy images; command={result}', flush=True)
    return result
