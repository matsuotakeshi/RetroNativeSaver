"""Software frame layout, DIB row packing and color conversion without Win32."""


def rotate_frame(frame_bytes, width, height, pitch, bytes_per_pixel, rotation):
    """Apply libretro's counter-clockwise quarter turns to top-down pixels.

    Preserve each pixel's bytes (including XRGB's unused byte). Slice whole
    channels at once instead of looping over individual pixels in Python.
    The output is tightly packed; DIB alignment remains pack_dib_rows' job.
    """
    if rotation == 0:
        return frame_bytes, width, height, pitch
    if rotation not in (1, 2, 3):
        raise ValueError('Invalid software frame rotation')
    if bytes_per_pixel not in (2, 4) or width <= 0 or height <= 0:
        raise ValueError('Invalid software frame dimensions or pixel size')
    row_bytes = width * bytes_per_pixel
    if pitch < row_bytes or len(frame_bytes) < (height - 1) * pitch + row_bytes:
        raise ValueError('Incomplete software frame or invalid pitch')
    out_w, out_h = (height, width) if rotation & 1 else (width, height)
    out_pitch = out_w * bytes_per_pixel
    packed = bytearray(out_pitch * out_h)
    for y in range(out_h):
        dst = y * out_pitch
        if rotation == 2:
            src = (height - 1 - y) * pitch
            for channel in range(bytes_per_pixel):
                packed[dst + channel:dst + out_pitch:bytes_per_pixel] = (
                    frame_bytes[src + channel:src + row_bytes:bytes_per_pixel][::-1])
        else:
            x = width - 1 - y if rotation == 1 else y
            src = x * bytes_per_pixel
            for channel in range(bytes_per_pixel):
                column = frame_bytes[src + channel:height * pitch:pitch]
                packed[dst + channel:dst + out_pitch:bytes_per_pixel] = (
                    column if rotation == 1 else column[::-1])
    return bytes(packed), out_w, out_h, out_pitch

def pack_dib_rows( frame_bytes: bytes, src_w: int, src_h: int,
                   src_pitch: int, bytes_per_pixel: int):
    """
    libretro's pitch is the byte distance between source rows and may be
    wider than width * bytes_per_pixel. StretchDIBits does not accept an
    explicit source pitch; it derives the row stride from biWidth/bpp.
    Repack each source row into the DIB stride expected by GDI.
    """
    row_bytes = src_w * bytes_per_pixel
    dib_stride = (row_bytes + 3) & ~3  # DWORD aligned

    # Fast path: source layout already matches what GDI expects.
    if src_pitch == dib_stride:
        expected = dib_stride * src_h
        return frame_bytes[:expected], dib_stride

    packed = bytearray(dib_stride * src_h)
    src = memoryview(frame_bytes)
    dst = memoryview(packed)

    for row in range(src_h):
        src_start = row * src_pitch
        src_end = src_start + row_bytes
        dst_start = row * dib_stride
        dst[dst_start:dst_start + row_bytes] = src[src_start:src_end]

    return bytes(packed), dib_stride

def colorref_from_hex(value: str, default="#B8B8B8"):
    s = str(value or default).strip().lstrip("#")
    if len(s) != 6:
        s = default.lstrip("#")
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        r, g, b = 216, 216, 216
    return r | (g << 8) | (b << 16)
