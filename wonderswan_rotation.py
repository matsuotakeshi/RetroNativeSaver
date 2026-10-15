"""Orientation flag: bit 0 of byte 6 in the final 10-byte cartridge header."""
def orientation_from_rom(path):
    with path.open('rb') as stream:
        stream.seek(0, 2)
        if stream.tell() < 10:
            raise ValueError('WonderSwan ROM header is missing')
        stream.seek(-4, 2)
        return 'portrait' if stream.read(1)[0] & 1 else 'landscape'
