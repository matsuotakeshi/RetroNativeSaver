"""One-line title scrolling on the existing GDI surface; no extra handles."""
from ctypes import byref
import math
import time

from gdi_safety import checked, selected


def number(value, default, maximum):
    try:
        value = float(value)
        return min(maximum, max(0.0, value)) if math.isfinite(value) else default
    except (ValueError, TypeError, OverflowError):
        return default


def positions(text_width, viewport, elapsed, speed=24, pause=2, gap=48):
    """Repeat leftwards, pausing when the next copy reaches the left edge."""
    if text_width <= 0 or viewport <= 0:
        return ()
    if speed <= 0:
        return (0,)
    distance = max(text_width, viewport) + gap
    phase = max(0, elapsed) % (pause + distance / speed)
    offset = int(max(0, phase - pause) * speed)
    return tuple(x for x in (-offset, distance - offset)
                 if x < viewport and x + text_width > 0)


def draw(owner, gdi, size_type, system, game, x, y, w, h, cfg):
    if not owner.mem_dc or not (system or game):
        return
    margin = max(0, int(cfg.get('margin', 6)))
    padding = max(0, int(cfg.get('padding', 4)))
    box_width, available_height = w - margin * 2, h - margin * 2
    viewport = box_width - padding * 2
    if viewport <= 0 or available_height <= padding * 2:
        return
    if not owner.overlay_system_font:
        owner.overlay_system_font = owner._create_overlay_font(cfg.get('system_font_size', 12), 8)
    dc = owner.mem_dc
    saved = checked('SaveDC', gdi.SaveDC, dc)
    try:
        selected(gdi.SelectObject, dc, owner.overlay_system_font)
        states = getattr(owner, '_overlay_scroll_states', None)
        if states is None:
            states = owner._overlay_scroll_states = {}
        slot = (x, y)
        identity = (system, game, owner.overlay_system_font, w, h, margin, padding)
        now = time.monotonic()
        state = states.get(slot)
        if state is None or state['identity'] != identity:
            parts = [(system + (' / ' if game else ''), 'system_color')] if system else []
            if game:
                parts.append((game, 'game_color'))
            runs, total, height = [], 0, 0
            for text, color in parts:
                # Win32 counts UTF-16 units, including surrogate pairs.
                units = len(text.encode('utf-16-le')) // 2
                size = size_type()
                checked('GetTextExtentPoint32W', gdi.GetTextExtentPoint32W,
                        dc, text, units, byref(size))
                runs.append((text, units, color, total))
                total += int(size.cx)
                height = max(height, int(size.cy))
            state = dict(identity=identity, start=now, runs=runs, width=total, height=height)
            # Retain only current measurements, with a bound for repeated layout changes.
            if slot not in states and len(states) >= 256:
                states.clear()
            states[slot] = state
        box_height = min(available_height, state['height'] + padding * 2)
        if state['width'] <= 0 or box_height <= padding * 2:
            return
        left, top = x + margin, y + margin
        checked('IntersectClipRect', gdi.IntersectClipRect, dc,
                left, top, left + box_width, top + box_height)
        owner._draw_overlay_background(left, top, box_width, box_height,
                                       int(cfg.get('background_alpha', 112)))
        checked('IntersectClipRect', gdi.IntersectClipRect, dc,
                left + padding, top + padding,
                left + box_width - padding, top + box_height - padding)
        checked('SetBkMode', gdi.SetBkMode, dc, 1)  # TRANSPARENT
        offsets = positions(state['width'], viewport, now - state['start'],
                            number(cfg.get('scroll_speed', 24), 24, 200),
                            number(cfg.get('scroll_pause_seconds', 2), 2, 60),
                            int(number(cfg.get('scroll_gap', 48), 48, 4096)))
        for offset in offsets:
            for text, units, color_key, advance in state['runs']:
                default = '#909090' if color_key == 'system_color' else '#B8B8B8'
                color = owner._colorref_from_hex(cfg.get(color_key, default))
                checked('SetTextColor', gdi.SetTextColor, dc, color,
                        invalid=(None, -1, 0xFFFFFFFF))
                checked('TextOutW', gdi.TextOutW, dc, left + padding + offset + advance,
                        top + padding, text, units)
    finally:
        checked('RestoreDC', gdi.RestoreDC, dc, saved)
