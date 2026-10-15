class GDIWindow:
    def _ensure_backbuffer(self, width: int, height: int):
        if width == self.mem_w and height == self.mem_h and self.mem_dc and self.mem_bitmap:
            return

        # Dispose old backing bitmap/DC first.
        self._dispose_overlay_bg_resources()

        if self.mem_dc:
            if self.mem_old_bitmap:
                gdi32.SelectObject(self.mem_dc, self.mem_old_bitmap)
                self.mem_old_bitmap = None
            if self.mem_bitmap:
                gdi32.DeleteObject(self.mem_bitmap)
                self.mem_bitmap = None
            gdi32.DeleteDC(self.mem_dc)
            self.mem_dc = None

        hdc = user32.GetDC(self.hwnd)
        try:
            self.mem_dc = gdi32.CreateCompatibleDC(hdc)
            if not self.mem_dc:
                raise ctypes.WinError()

            self.mem_bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
            if not self.mem_bitmap:
                raise ctypes.WinError()

            self.mem_old_bitmap = gdi32.SelectObject(self.mem_dc, self.mem_bitmap)
            self.mem_w = width
            self.mem_h = height
        finally:
            user32.ReleaseDC(self.hwnd, hdc)


    def _dispose_overlay_bg_resources(self):
        if self.overlay_bg_dc:
            try:
                if self.overlay_bg_old_bitmap:
                    gdi32.SelectObject(self.overlay_bg_dc, self.overlay_bg_old_bitmap)
                    self.overlay_bg_old_bitmap = None
                if self.overlay_bg_bitmap:
                    gdi32.DeleteObject(self.overlay_bg_bitmap)
                    self.overlay_bg_bitmap = None
                gdi32.DeleteDC(self.overlay_bg_dc)
            except Exception:
                pass
            self.overlay_bg_dc = None


    def _ensure_overlay_bg_resources(self):
        if self.overlay_bg_dc and self.overlay_bg_bitmap:
            return

        if not self.mem_dc:
            return

        self.overlay_bg_dc = gdi32.CreateCompatibleDC(self.mem_dc)
        if not self.overlay_bg_dc:
            self.overlay_bg_dc = None
            return

        self.overlay_bg_bitmap = gdi32.CreateCompatibleBitmap(self.mem_dc, 1, 1)
        if not self.overlay_bg_bitmap:
            gdi32.DeleteDC(self.overlay_bg_dc)
            self.overlay_bg_dc = None
            return

        self.overlay_bg_old_bitmap = gdi32.SelectObject(self.overlay_bg_dc, self.overlay_bg_bitmap)
        black = RECT(0, 0, 1, 1)
        brush = gdi32.GetStockObject(BLACK_BRUSH)
        user32.FillRect(self.overlay_bg_dc, byref(black), brush)


    def _draw_overlay_background(self, x: int, y: int, w: int, h: int, alpha: int):
        if w <= 0 or h <= 0:
            return

        alpha = max(0, min(255, int(alpha)))
        if alpha <= 0:
            return

        box = RECT(x, y, x + w, y + h)

        if alpha >= 255:
            brush = gdi32.GetStockObject(BLACK_BRUSH)
            user32.FillRect(self.mem_dc, byref(box), brush)
            return

        self._ensure_overlay_bg_resources()
        if not self.overlay_bg_dc:
            brush = gdi32.GetStockObject(BLACK_BRUSH)
            user32.FillRect(self.mem_dc, byref(box), brush)
            return

        blend = BLENDFUNCTION(AC_SRC_OVER, 0, alpha, 0)
        ok = msimg32.AlphaBlend(
            self.mem_dc, x, y, w, h,
            self.overlay_bg_dc, 0, 0, 1, 1,
            blend,
        )
        if not ok:
            brush = gdi32.GetStockObject(BLACK_BRUSH)
            user32.FillRect(self.mem_dc, byref(box), brush)


    def _draw_overlay_line(self, text_value: str, font: HFONT, color: int,
                           x: int, y: int, padding: int, background_alpha: int):
        if not text_value or not font:
            return 0

        old_font = gdi32.SelectObject(self.mem_dc, font)
        try:
            size = SIZE()
            if not gdi32.GetTextExtentPoint32W(
                self.mem_dc, text_value, len(text_value), byref(size)
            ):
                return 0

            box_w = int(size.cx) + padding * 2
            box_h = int(size.cy) + padding * 2
            self._draw_overlay_background(
                x,
                y,
                box_w,
                box_h,
                background_alpha,
            )

            gdi32.SetBkMode(self.mem_dc, TRANSPARENT)
            gdi32.SetTextColor(self.mem_dc, color)
            gdi32.TextOutW(
                self.mem_dc,
                x + padding,
                y + padding,
                text_value,
                len(text_value),
            )
            return int(size.cy) + padding * 2
        finally:
            gdi32.SelectObject(self.mem_dc, old_font)


    def close(self):
        self._unregister_power_notification()
        self._dispose_overlay_bg_resources()

        if self.overlay_system_font:
            try:
                gdi32.DeleteObject(self.overlay_system_font)
            except Exception:
                pass
            self.overlay_system_font = None

        if self.overlay_game_font:
            try:
                gdi32.DeleteObject(self.overlay_game_font)
            except Exception:
                pass
            self.overlay_game_font = None

        if self.mem_dc:
            try:
                if self.mem_old_bitmap:
                    gdi32.SelectObject(self.mem_dc, self.mem_old_bitmap)
                    self.mem_old_bitmap = None
                if self.mem_bitmap:
                    gdi32.DeleteObject(self.mem_bitmap)
                    self.mem_bitmap = None
                gdi32.DeleteDC(self.mem_dc)
                self.mem_dc = None
            except Exception:
                pass

        if self.cursor_hidden:
            try:
                user32.ShowCursor(True)
            except Exception:
                pass
            self.cursor_hidden = False
        if self.hwnd:
            try:
                user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            self.hwnd = None


