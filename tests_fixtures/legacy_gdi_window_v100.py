class GDIWindow:
    def __init__(
        self,
        width=1280,
        height=720,
        fullscreen=False,
        mouse_exit_threshold=12,
        parent_hwnd=None,
        preview_mode=False,
        hide_cursor=True,
        embedded_rect=None,
    ):
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.mouse_exit_threshold = mouse_exit_threshold
        self.parent_hwnd = HWND(parent_hwnd) if parent_hwnd else None
        self.preview_mode = bool(preview_mode)
        self.hide_cursor = bool(hide_cursor)
        self.embedded_rect = embedded_rect
        self.cursor_hidden = False
        self.should_close = False
        self.first_mouse = None
        self.power_notification = None
        self.display_was_off = False
        self.display_was_dimmed = False
        self.exit_on_display_off = False
        self.hold_on_display_power = False
        self.power_idle = False
        self.exit_reason = "input"
        self.hwnd = None
        self.mem_dc = None
        self.mem_bitmap = None
        self.mem_old_bitmap = None
        self.mem_w = 0
        self.mem_h = 0
        self.virtual_left = 0
        self.virtual_top = 0
        self.virtual_width = width
        self.virtual_height = height
        self.overlay_system_font = None
        self.overlay_game_font = None
        self.overlay_bg_dc = None
        self.overlay_bg_bitmap = None
        self.overlay_bg_old_bitmap = None
        self._class_name = "RetroNativeSaverWindow"
        self._wndproc = WNDPROC(self._proc)


    def _note_exit(self, hwnd, reason, details=""):
        # Keep the originating reason through WM_CLOSE/WM_DESTROY/WM_QUIT.
        if not self.should_close:
            self.exit_reason = reason
        print(f"[exit-diagnostic] event={reason} origin={self.exit_reason} "
              f"hwnd={hwnd} class={getattr(self, '_class_name', '')} "
              f"parent={getattr(self, 'parent_hwnd', None)} "
              f"fullscreen={self.fullscreen} preview={self.preview_mode} "
              f"standby={getattr(self, 'power_idle', False)} {details}", flush=True)


    def _request_display_exit(self, hwnd, reason):
        if not self.should_close:
            self._note_exit(hwnd, reason)
            self.should_close = True
            print(f"[display-power] {reason}; closing saver", flush=True)
            # Hide immediately; the supervisor's existing Job Object cleanup
            # terminates even a worker blocked inside a graphics driver call.
            user32.ShowWindow(hwnd, SW_HIDE)
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


    def _unregister_power_notification(self):
        if self.power_notification:
            user32.UnregisterPowerSettingNotification(self.power_notification)
            self.power_notification = None


    def _proc(self, hwnd, msg, wparam, lparam):
        if self.fullscreen and not self.preview_mode:
            if msg == WM_DISPLAYCHANGE and not getattr(self, "power_idle", False):
                self._request_display_exit(hwnd, "display-configuration-changed")
                return 0
            if msg == WM_POWERBROADCAST:
                if wparam == PBT_POWERSETTINGCHANGE and lparam:
                    event = ctypes.cast(lparam, POINTER(PowerBroadcastSetting)).contents
                    if bytes(event.guid) == SESSION_DISPLAY_GUID and event.length == 4:
                        state = int(event.state)
                        print(f"[display-power] session display state={state}", flush=True)
                        if state in (0, 2) and getattr(self, "hold_on_display_power", False):
                            self.display_was_dimmed = state == 2
                            self.display_was_off = state == 0
                            if not self.power_idle:
                                self.power_idle = True
                                print("[display-power] standby requested; stopping emulators, keeping saver alive", flush=True)
                            return 1
                        if state == 1 and getattr(self, "power_idle", False):
                            self.display_was_dimmed = False
                            self.display_was_off = False
                            self._request_display_exit(hwnd, "display-resumed-from-standby")
                            return 1
                        if state == 2:
                            self.display_was_dimmed = True
                            if self.exit_on_display_off:
                                self._request_display_exit(hwnd, "display-dimmed")
                        elif state == 0:
                            self.display_was_off = True
                            if self.exit_on_display_off:
                                self._request_display_exit(hwnd, "display-off")
                        elif state == 1:
                            self.display_was_dimmed = False
                            if self.display_was_off:
                                self.display_was_off = False
                                self._request_display_exit(hwnd, "display-resumed")
                elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                    self._request_display_exit(hwnd, "system-resumed")
                return 1
        if not self.preview_mode and msg in (
            WM_KEYDOWN, WM_SYSKEYDOWN, WM_LBUTTONDOWN,
            WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_MOUSEWHEEL
        ):
            names = {WM_KEYDOWN: "key-down", WM_SYSKEYDOWN: "system-key-down",
                     WM_LBUTTONDOWN: "left-button", WM_RBUTTONDOWN: "right-button",
                     WM_MBUTTONDOWN: "middle-button", WM_MOUSEWHEEL: "mouse-wheel"}
            self._note_exit(hwnd, names[msg], f"message=0x{msg:04X}")
            self.should_close = True
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0
        if not self.preview_mode and msg == WM_MOUSEMOVE:
            # Tile replacement can deliver a synthetic/local-coordinate jump.
            # Confirm movement using the cursor in the shared screen coordinate space.
            lp32 = int(lparam) & 0xFFFFFFFF
            message_x = ctypes.c_short(lp32 & 0xFFFF).value
            message_y = ctypes.c_short((lp32 >> 16) & 0xFFFF).value
            point = POINT()
            if not user32.GetCursorPos(byref(point)):
                if not getattr(self, "cursor_read_failed", False):
                    print(f"[exit-diagnostic] GetCursorPos failed hwnd={hwnd}; mouse notification ignored", flush=True)
                self.cursor_read_failed = True
                return 0
            self.cursor_read_failed = False
            x, y = int(point.x), int(point.y)
            if self.first_mouse is None:
                self.first_mouse = (x, y)
                print(f"[exit-diagnostic] mouse-baseline hwnd={hwnd} space=screen x={x} y={y}", flush=True)
            else:
                sx, sy = self.first_mouse
                if abs(x - sx) + abs(y - sy) >= self.mouse_exit_threshold:
                    self._note_exit(hwnd, "mouse-move",
                        f"space=screen message=({message_x},{message_y}) start=({sx},{sy}) current=({x},{y}) delta=({x-sx},{y-sy}) "
                        f"distance={abs(x-sx)+abs(y-sy)} threshold={self.mouse_exit_threshold}")
                    self.should_close = True
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0
        if msg == WM_ERASEBKGND:
            # v0.3: suppress visible background erase. Frames are presented
            # from an off-screen buffer in one BitBlt operation.
            return 1
        if msg == WM_CLOSE:
            self._note_exit(hwnd, "WM_CLOSE")
            self.should_close = True
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self._note_exit(hwnd, "WM_DESTROY")
            self._unregister_power_notification()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


    def create(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = ctypes.cast(self._wndproc, c_void_p).value
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, c_void_p(IDC_ARROW))
        wc.hbrBackground = 0
        wc.lpszClassName = self._class_name
        atom = user32.RegisterClassW(byref(wc))
        if not atom and ctypes.get_last_error() != 1410:  # already exists
            raise ctypes.WinError()

        parent = None

        if self.parent_hwnd:
            # The Windows Settings preview host can disappear between process
            # startup and child-window creation. Treat that as a normal exit.
            if not user32.IsWindow(self.parent_hwnd):
                self.should_close = True
                print("[preview] parent window disappeared before create()", flush=True)
                return False

            r = RECT()
            if not user32.GetClientRect(self.parent_hwnd, byref(r)):
                if not user32.IsWindow(self.parent_hwnd):
                    self.should_close = True
                    print(
                        "[preview] parent window disappeared before GetClientRect()",
                        flush=True,
                    )
                    return False
                raise ctypes.WinError()

            self.virtual_left = 0
            self.virtual_top = 0
            self.virtual_width = max(1, int(r.right - r.left))
            self.virtual_height = max(1, int(r.bottom - r.top))

            x = 0
            y = 0
            w = self.virtual_width
            h = self.virtual_height
            style = WS_CHILD | WS_VISIBLE
            ex_style = 0
            parent = self.parent_hwnd
            if self.embedded_rect is not None:
                x, y, w, h = map(int, self.embedded_rect)
                self.virtual_width, self.virtual_height = w, h

        elif self.fullscreen:
            self.virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            self.virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            self.virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            self.virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

            x = self.virtual_left
            y = self.virtual_top
            w = self.virtual_width
            h = self.virtual_height
            style = WS_POPUP
            ex_style = WS_EX_TOPMOST

        else:
            self.virtual_left = 0
            self.virtual_top = 0
            self.virtual_width = self.width
            self.virtual_height = self.height

            x = y = CW_USEDEFAULT
            w, h = self.width, self.height
            style = WS_OVERLAPPEDWINDOW
            ex_style = 0

        self.hwnd = user32.CreateWindowExW(
            ex_style, self._class_name, "Retro Native Saver v0.20.100", style | 0x02000000,
            x, y, w, h, parent, None, hinst, None
        )
        if not self.hwnd:
            raise ctypes.WinError()
        if self.fullscreen and not self.preview_mode:
            guid = (ctypes.c_ubyte * 16).from_buffer_copy(SESSION_DISPLAY_GUID)
            self.power_notification = user32.RegisterPowerSettingNotification(
                self.hwnd, byref(guid), 0)
            if self.power_notification:
                print("[display-power] session notifications registered", flush=True)
            else:
                print("[display-power] notification registration failed", flush=True)
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        if not self.preview_mode and self.hide_cursor:
            user32.ShowCursor(False)
            self.cursor_hidden = True

        return True


    def pump(self):
        guard = getattr(self, "supervisor_guard", None)
        if guard is not None:
            guard.beat()
        msg = MSG()
        while user32.PeekMessageW(byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == 0x0012:  # WM_QUIT
                self._note_exit(getattr(self, "hwnd", None), "WM_QUIT")
                self.should_close = True
                return
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))


