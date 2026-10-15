"""Disposable cards for saver sessions; never reuse the player's save files.

PS2 layout and ECC follow Ross Ridge's public-domain mymc format:
https://github.com/ps2dev/mymc (ps2mc.py, ps2mc_dir.py, ps2mc_ecc.py).
"""
from functools import lru_cache
import ctypes
from pathlib import Path
import shutil
import struct


def ecc128(data):
    column, line0, line1 = 0x77, 0x7f, 0x7f
    masks = (0x55, 0x33, 0x0f, 0, 0xaa, 0xcc, 0xf0)
    for i, b in enumerate(data):
        column ^= sum(((b & mask).bit_count() & 1) << bit for bit, mask in enumerate(masks))
        if b.bit_count() & 1:
            line0 ^= ~i
            line1 ^= i
    return bytes((column, line0 & 0x7f, line1))


@lru_cache(maxsize=128)
def raw_page(data):
    return data + b''.join(ecc128(data[i:i+128]) for i in range(0, 512, 128)) + bytes(4)


def empty_ps2_card():
    """8 MiB, 512+16-byte pages, empty formatted root and 8,134 free clusters."""
    data = bytearray(8 * 1024 * 1024)
    # IFC=8, FAT=9..40, allocatable clusters=41..8175; last 2 erase blocks reserved.
    header = struct.pack('<28s12sHHHHLLLLLL8x128s128sbbxx',
                         b'Sony PS2 Memory Card Format ', b'1.2.0.0', 512, 2, 16, 0xff00,
                         8192, 41, 8135, 0, 1023, 1022,
                         struct.pack('<32I', 8, *([0]*31)), b'\xff'*128, 2, 0x2b)
    data[:len(header)] = header
    data[8*1024:9*1024] = struct.pack('<256I', *range(9, 41), *([0xffffffff]*224))
    fat = [0xffffffff] + [0x7fffffff]*8134 + [0xffffffff]*(8192-8135)
    data[9*1024:41*1024] = struct.pack('<8192I', *fat)
    date = struct.pack('<xBBBBBH', 0, 0, 0, 1, 1, 2000)
    for index, (name, mode, length) in enumerate(((b'.', 0x8427, 2), (b'..', 0xa426, 0))):
        entry = struct.pack('<HHL8sLL8sL28x448s', mode, 0, length, date, 0, 0, date, 0, name)
        start = 41*1024 + index*512
        data[start:start+512] = entry
    result = bytearray().join(raw_page(bytes(data[i:i+512])) for i in range(0, len(data), 512))
    result[1022*16*528:1023*16*528] = b'\xff'*(16*528)
    return bytes(result)


def prepare(system, original_system, slot_dir):
    """Return isolated system/save roots and a fresh options mapping."""
    sid = system['id']
    target = Path(slot_dir) / 'card_environment'
    target.mkdir()  # Must be fresh: do not overwrite a previous session's files.
    system_dir, save_dir = target / 'system', target / 'save'
    save_dir.mkdir()
    options = dict(system.get('core_options', {}))
    source = Path(original_system)
    if sid == 'dreamcast':
        dc = system_dir / 'dc'
        dc.mkdir(parents=True)
        for path in (source / 'dc').iterdir():
            if path.is_file() and (path.name.lower() in {'dc_boot.bin', 'dc_flash.bin', 'naomi_boot.bin'} or path.suffix.lower() == '.zip'):
                shutil.copyfile(path, dc / path.name)
        # Flycast initialises missing VMUs with its own formatted empty image.
        # Never precreate zero-filled files: older Flycast treats them as existing
        # unformatted cards and replaces its in-memory default with those zeros.
        # Disable per-content paths so all versions use this disposable system/dc.
        options.update(reicast_per_content_vmus='disabled', flycast_per_content_vmus='disabled')
        options.update(reicast_device_port1_slot1='VMU', flycast_device_port1_slot1='VMU')
        print('[memory-card] Dreamcast: isolated VMU A1; core creates formatted empty card', flush=True)
    elif sid == 'ps2':
        ps2 = system_dir / 'pcsx2'
        ps2.mkdir(parents=True)
        for folder in ('bios', 'resources'):
            if (source / 'pcsx2' / folder).is_dir():
                shutil.copytree(source / 'pcsx2' / folder, ps2 / folder)
        for name in ('GameIndex.dbf', 'GameIndex.yaml'):
            if (source / 'pcsx2' / name).is_file():
                shutil.copyfile(source / 'pcsx2' / name, ps2 / name)
        cards = ps2 / 'memcards'
        cards.mkdir()
        image = empty_ps2_card()
        for number in (1, 2):
            (cards / f'Mcd{number:03}.ps2').write_bytes(image)
        options['pcsx2_shared_memory_cards'] = 'enabled'
        print('[memory-card] PS2: isolated formatted 8 MiB cards in slots 1 and 2', flush=True)
    else:
        raise ValueError(f'Unsupported disposable memory-card system: {sid}')
    print(f'[memory-card] system={system_dir} save={save_dir}', flush=True)
    return system_dir, save_dir, options


def attach_controller(dll, ports=4):
    # Dreamcast VMUs attach to a controller, not directly to the console.
    # No buttons are pressed: the frontend's input callback still returns zero.
    setter = dll.retro_set_controller_port_device
    setter.argtypes = [ctypes.c_uint, ctypes.c_uint]
    setter.restype = None
    # Flycast waits until ALL ports are initialized before applying VMU options.
    for port in range(ports):
        setter(port, 1 if port == 0 else 0)  # JOYPAD on port 1; NONE elsewhere
    print('[memory-card] controller attached to port 1 (no automatic input)', flush=True)
