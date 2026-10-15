class BITMAPINFOHEADER(Structure):
    _fields_ = [
        ("biSize", c_ulong), ("biWidth", c_long), ("biHeight", c_long), ("biPlanes", c_ushort),
        ("biBitCount", c_ushort), ("biCompression", c_ulong), ("biSizeImage", c_ulong),
        ("biXPelsPerMeter", c_long), ("biYPelsPerMeter", c_long), ("biClrUsed", c_ulong), ("biClrImportant", c_ulong)
    ]


class RGBQUAD(Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte), ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]


class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


class BITMAPINFO_MASKS(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("masks", c_ulong * 3)]


class GDIWindow:










    def _fit_inside(self, src_w: int, src_h: int, display_aspect: float,
                    x: int, y: int, w: int, h: int):
        from screen_layout import fit_inside
        return fit_inside(src_w, src_h, display_aspect, x, y, w, h)

    def _pack_dib_rows(self, frame_bytes: bytes, src_w: int, src_h: int,
                       src_pitch: int, bytes_per_pixel: int):
        from frame_format import pack_dib_rows
        return pack_dib_rows(frame_bytes, src_w, src_h, src_pitch, bytes_per_pixel)

    def draw_frame_to_rect(self, frame_bytes: bytes, src_w: int, src_h: int,
                           src_pitch: int, pixel_format: int, display_aspect: float,
                           x: int, y: int, w: int, h: int, bottom_up: bool = False):
        if not self.hwnd or not frame_bytes:
            return

        dx, dy, dw, dh = self._fit_inside(
            src_w, src_h, display_aspect, x, y, w, h
        )
        gdi32.SetStretchBltMode(self.mem_dc, HALFTONE)

        bytes_per_pixel = 4 if pixel_format == RETRO_PIXEL_FORMAT_XRGB8888 else 2
        dib_bytes, dib_stride = self._pack_dib_rows(
            frame_bytes, src_w, src_h, src_pitch, bytes_per_pixel
        )
        buf = ctypes.create_string_buffer(dib_bytes)

        if pixel_format == RETRO_PIXEL_FORMAT_XRGB8888:
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = src_w
            bmi.bmiHeader.biHeight = src_h if bottom_up else -src_h
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB
            bmi.bmiHeader.biSizeImage = dib_stride * src_h
            bmi_ptr = byref(bmi)

        else:
            bmi = BITMAPINFO_MASKS()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = src_w
            bmi.bmiHeader.biHeight = src_h if bottom_up else -src_h
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 16
            bmi.bmiHeader.biCompression = BI_BITFIELDS
            bmi.bmiHeader.biSizeImage = dib_stride * src_h

            if pixel_format == RETRO_PIXEL_FORMAT_RGB565:
                bmi.masks[0] = 0xF800
                bmi.masks[1] = 0x07E0
                bmi.masks[2] = 0x001F
            else:  # 0RGB1555
                bmi.masks[0] = 0x7C00
                bmi.masks[1] = 0x03E0
                bmi.masks[2] = 0x001F
            bmi_ptr = byref(bmi)

        gdi32.StretchDIBits(
            self.mem_dc,
            dx, dy, dw, dh,
            0, 0, src_w, src_h,
            buf, bmi_ptr, DIB_RGB_COLORS, SRCCOPY
        )





    def _ensure_overlay_fonts(self, system_px: int, game_px: int):
        if not self.overlay_system_font:
            self.overlay_system_font = gdi32.CreateFontW(
                -max(8, int(system_px)), 0, 0, 0, FW_NORMAL,
                False, False, False,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                DEFAULT_QUALITY, DEFAULT_PITCH | FF_DONTCARE,
                "Segoe UI",
            )
        if not self.overlay_game_font:
            self.overlay_game_font = gdi32.CreateFontW(
                -max(9, int(game_px)), 0, 0, 0, FW_NORMAL,
                False, False, False,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                DEFAULT_QUALITY, DEFAULT_PITCH | FF_DONTCARE,
                "Segoe UI",
            )






