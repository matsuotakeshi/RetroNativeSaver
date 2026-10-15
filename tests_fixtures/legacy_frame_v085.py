"""Unchanged GDIWindow calculations with unused self removed, test only."""

def fit_inside( src_w: int, src_h: int, display_aspect: float,
                x: int, y: int, w: int, h: int):
    if src_w <= 0 or src_h <= 0:
        return x, y, w, h

    # libretro framebuffer pixels are not necessarily square.
    # Prefer the core-reported display aspect ratio (SNES is typically
    # close to 4:3) and only fall back to raw framebuffer dimensions when
    # the core does not provide one.
    aspect = float(display_aspect) if display_aspect and display_aspect > 0 else (src_w / src_h)
    slot_aspect = w / h if h > 0 else aspect

    if slot_aspect > aspect:
        draw_h = h
        draw_w = max(1, int(round(h * aspect)))
    else:
        draw_w = w
        draw_h = max(1, int(round(w / aspect)))

    return x + (w - draw_w) // 2, y + (h - draw_h) // 2, draw_w, draw_h

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
