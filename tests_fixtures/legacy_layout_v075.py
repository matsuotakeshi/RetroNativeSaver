"""Frozen v0.20.75 layout calculations; tests only."""

def auto_grid_for_monitor(width: int, height: int):
    # Same layout family used by the established RetroArch-based saver.
    if width >= 3800 and height >= 2000:
        return 4, 4
    if width >= 3300 and height >= 1300:
        return 4, 3
    if width >= 2500 and height >= 1300:
        return 3, 3
    if width >= 2500 and height >= 1000:
        return 4, 2
    return 2, 2

def build_monitor_slots(monitor_rects, virtual_left, virtual_top, gap_pixels=0,
                        max_slots_per_monitor=16):
    slots = []

    for monitor_index, (left, top, right, bottom) in enumerate(monitor_rects):
        width = right - left
        height = bottom - top
        cols, rows = auto_grid_for_monitor(width, height)

        requested = cols * rows
        if requested > max_slots_per_monitor:
            # Conservative fallback if a future display rule exceeds the cap.
            while cols * rows > max_slots_per_monitor and cols > 1:
                cols -= 1
            while cols * rows > max_slots_per_monitor and rows > 1:
                rows -= 1

        local_left = left - virtual_left
        local_top = top - virtual_top

        print(
            f"[display] monitor {monitor_index} rect=({left}, {top}, {right}, {bottom}) "
            f"auto layout={cols}x{rows} slots={cols * rows}"
        )

        for row in range(rows):
            y0 = local_top + (height * row) // rows
            y1 = local_top + (height * (row + 1)) // rows

            for col in range(cols):
                x0 = local_left + (width * col) // cols
                x1 = local_left + (width * (col + 1)) // cols

                x = x0 + gap_pixels
                y = y0 + gap_pixels
                w = max(1, (x1 - x0) - gap_pixels * 2)
                h = max(1, (y1 - y0) - gap_pixels * 2)
                slots.append((x, y, w, h))

    print(f"[display] total slots={len(slots)}")
    return slots

def build_windowed_slots(width: int, height: int, count: int, gap_pixels=0):
    if count <= 1:
        return [(0, 0, width, height)]

    if count <= 4:
        cols, rows = 2, 2
    else:
        cols = 4
        rows = (count + cols - 1) // cols

    rects = []
    for n in range(count):
        col = n % cols
        row = n // cols
        x0 = (width * col) // cols
        x1 = (width * (col + 1)) // cols
        y0 = (height * row) // rows
        y1 = (height * (row + 1)) // rows
        rects.append((
            x0 + gap_pixels,
            y0 + gap_pixels,
            max(1, x1 - x0 - gap_pixels * 2),
            max(1, y1 - y0 - gap_pixels * 2),
        ))
    return rects
