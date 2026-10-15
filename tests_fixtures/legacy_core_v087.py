RETRO_API_VERSION = 1
RETRO_ENVIRONMENT_GET_CAN_DUPE = 3
RETRO_ENVIRONMENT_SET_ROTATION = 1
RETRO_ENVIRONMENT_GET_RUMBLE_INTERFACE = 23
RETRO_ENVIRONMENT_SET_CONTROLLER_INFO = 35
RETRO_ENVIRONMENT_GET_FASTFORWARDING = 0x10000 | 49
RETRO_ENVIRONMENT_GET_INPUT_BITMASKS = 0x10000 | 51
RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY = 9
RETRO_ENVIRONMENT_SET_PIXEL_FORMAT = 10
RETRO_ENVIRONMENT_GET_VARIABLE = 15
RETRO_ENVIRONMENT_SET_VARIABLES = 16
RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE = 17
RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY = 30
RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY = 31
RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO = 32
RETRO_ENVIRONMENT_SET_GEOMETRY = 37
RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION = 52
RETRO_ENVIRONMENT_SET_HW_RENDER = 14
RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER = 56

RETRO_HW_CONTEXT_NONE = 0
RETRO_HW_CONTEXT_OPENGL = 1
RETRO_HW_CONTEXT_OPENGL_CORE = 3
RETRO_HW_FRAME_BUFFER_VALID = ctypes.c_void_p(-1).value
RETRO_ENVIRONMENT_SET_CORE_OPTIONS = 53
RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL = 54
RETRO_ENVIRONMENT_SET_CORE_OPTIONS_DISPLAY = 55
RETRO_ENVIRONMENT_GET_LOG_INTERFACE = 27
RETRO_ENVIRONMENT_GET_PERF_INTERFACE = 28
RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK = 12
RETRO_ENVIRONMENT_SET_DISK_CONTROL_INTERFACE = 13
RETRO_ENVIRONMENT_GET_DISK_CONTROL_INTERFACE_VERSION = 57
RETRO_ENVIRONMENT_SET_DISK_CONTROL_EXT_INTERFACE = 58
RETRO_ENVIRONMENT_SET_SAVE_STATE_IN_BACKGROUND = 69
RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT = 0x10000 | 44

RETRO_PIXEL_FORMAT_0RGB1555 = 0
RETRO_PIXEL_FORMAT_XRGB8888 = 1
RETRO_PIXEL_FORMAT_RGB565 = 2

class RetroGameInfo(Structure):
    _fields_ = [("path", c_char_p), ("data", c_void_p), ("size", c_size_t), ("meta", c_char_p)]

class RetroSystemInfo(Structure):
    _fields_ = [
        ("library_name", c_char_p), ("library_version", c_char_p),
        ("valid_extensions", c_char_p), ("need_fullpath", c_bool), ("block_extract", c_bool)
    ]

class RetroGameGeometry(Structure):
    _fields_ = [("base_width", c_uint), ("base_height", c_uint), ("max_width", c_uint), ("max_height", c_uint), ("aspect_ratio", c_float)]

class RetroSystemTiming(Structure):
    _fields_ = [("fps", c_double), ("sample_rate", c_double)]

class RetroSystemAVInfo(Structure):
    _fields_ = [("geometry", RetroGameGeometry), ("timing", RetroSystemTiming)]

class RetroVariable(Structure):
    _fields_ = [("key", c_char_p), ("value", c_char_p)]

EnvironmentCallback = CFUNCTYPE(c_bool, c_uint, c_void_p)
VideoRefreshCallback = CFUNCTYPE(None, c_void_p, c_uint, c_uint, c_size_t)
AudioSampleCallback = CFUNCTYPE(None, c_int16, c_int16)
AudioSampleBatchCallback = CFUNCTYPE(c_size_t, POINTER(c_int16), c_size_t)
InputPollCallback = CFUNCTYPE(None)
InputStateCallback = CFUNCTYPE(c_int16, c_uint, c_uint, c_uint, c_uint)

RetroHWContextResetCallback = CFUNCTYPE(None)

RetroLogPrintfCallback = CFUNCTYPE(None, c_int, c_char_p)
RetroPerfGetTimeUsecCallback = CFUNCTYPE(c_int64)
RetroPerfGetCpuFeaturesCallback = CFUNCTYPE(c_uint64)
RetroPerfGetCounterCallback = CFUNCTYPE(c_uint64)

class RetroLogCallback(Structure):
    _fields_ = [("log", c_void_p)]

class RetroPerfCounter(Structure):
    _fields_ = [
        ("ident", c_char_p),
        ("start", c_uint64),
        ("total", c_uint64),
        ("call_cnt", c_uint64),
        ("registered", c_bool),
    ]

RetroPerfRegisterCallback = CFUNCTYPE(None, POINTER(RetroPerfCounter))
RetroPerfStartCallback = CFUNCTYPE(None, POINTER(RetroPerfCounter))
RetroPerfStopCallback = CFUNCTYPE(None, POINTER(RetroPerfCounter))
RetroPerfLogCallback = CFUNCTYPE(None)

class RetroPerfCallback(Structure):
    _fields_ = [
        ("get_time_usec", c_void_p),
        ("get_cpu_features", c_void_p),
        ("get_perf_counter", c_void_p),
        ("perf_register", c_void_p),
        ("perf_start", c_void_p),
        ("perf_stop", c_void_p),
        ("perf_log", c_void_p),
    ]

class RetroKeyboardCallback(Structure):
    _fields_ = [("callback", c_void_p)]

class RetroDiskControlCallback(Structure):
    _fields_ = [
        ("set_eject_state", c_void_p),
        ("get_eject_state", c_void_p),
        ("get_image_index", c_void_p),
        ("set_image_index", c_void_p),
        ("get_num_images", c_void_p),
        ("replace_image_index", c_void_p),
        ("add_image_index", c_void_p),
    ]

class RetroDiskControlExtCallback(Structure):
    _fields_ = [
        ("set_eject_state", c_void_p),
        ("get_eject_state", c_void_p),
        ("get_image_index", c_void_p),
        ("set_image_index", c_void_p),
        ("get_num_images", c_void_p),
        ("replace_image_index", c_void_p),
        ("add_image_index", c_void_p),
        ("set_initial_image", c_void_p),
        ("get_image_path", c_void_p),
        ("get_image_label", c_void_p),
    ]

RetroHWGetCurrentFramebufferCallback = CFUNCTYPE(c_size_t)
RetroHWGetProcAddressCallback = CFUNCTYPE(c_void_p, c_char_p)

class RetroHWRenderCallback(Structure):
    _fields_ = [
        ("context_type", c_uint),
        ("context_reset", c_void_p),
        ("get_current_framebuffer", c_void_p),
        ("get_proc_address", c_void_p),
        ("depth", c_bool),
        ("stencil", c_bool),
        ("bottom_left_origin", c_bool),
        ("version_major", c_uint),
        ("version_minor", c_uint),
        ("cache_context", c_bool),
        ("context_destroy", c_void_p),
        ("debug_context", c_bool),
    ]

# ---------------- Win32 GDI / WGL
class LibretroCore:

    def _bind_api(self):
        d = self.dll
        d.retro_api_version.restype = c_uint
        d.retro_set_environment.argtypes = [EnvironmentCallback]
        d.retro_set_video_refresh.argtypes = [VideoRefreshCallback]
        d.retro_set_audio_sample.argtypes = [AudioSampleCallback]
        d.retro_set_audio_sample_batch.argtypes = [AudioSampleBatchCallback]
        d.retro_set_input_poll.argtypes = [InputPollCallback]
        d.retro_set_input_state.argtypes = [InputStateCallback]
        d.retro_get_system_info.argtypes = [POINTER(RetroSystemInfo)]
        d.retro_get_system_av_info.argtypes = [POINTER(RetroSystemAVInfo)]
        d.retro_load_game.argtypes = [POINTER(RetroGameInfo)]
        d.retro_load_game.restype = c_bool

    def _install_callbacks(self):
        @EnvironmentCallback
        def env(cmd, data):
            if (
                self.env_trace_frames > 0
                and 0 < self._run_frame_index <= self.env_trace_frames
            ):
                print(
                    f"[env-frame {self._run_frame_index}] "
                    f"cmd={int(cmd)} {ENV_NAMES.get(int(cmd), '?')} "
                    f"data=0x{int(data or 0):X}",
                    flush=True,
                )
            if cmd == RETRO_ENVIRONMENT_GET_CAN_DUPE:
                ctypes.cast(data, POINTER(c_bool))[0] = True; return True
            if cmd == RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
                ctypes.cast(data, POINTER(c_char_p))[0] = self._system_dir_cstr; return True
            if cmd == RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
                ctypes.cast(data, POINTER(c_char_p))[0] = self._save_dir_cstr; return True
            if cmd == RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY:
                ctypes.cast(data, POINTER(c_char_p))[0] = self._assets_dir_cstr; return True

            if cmd == RETRO_ENVIRONMENT_SET_ROTATION:
                # Beetle WonderSwan rotates pixels and updates geometry itself
                # when frontend rotation is unavailable. Do not claim support.
                if self.system_info is not None and "WonderSwan" in decode_cstr(self.system_info.library_name):
                    return False
                # Dreamcast content used here is horizontal; accept the request.
                return True

            if cmd == RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:
                # No gameplay input UI is exposed by the screen saver.
                return True

            if cmd == RETRO_ENVIRONMENT_GET_RUMBLE_INTERFACE:
                # Rumble is irrelevant for a non-interactive screen saver.
                return False

            if cmd == RETRO_ENVIRONMENT_GET_FASTFORWARDING:
                if data:
                    ctypes.cast(data, POINTER(c_bool))[0] = False
                    return True
                return False

            if cmd == RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:
                # We do not expose libretro joypad bitmask input.
                return False

            if cmd == RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
                # retro_log_printf_t is a C variadic printf-style callback.
                # ctypes cannot safely implement a true variadic callback.
                # Diagnostic builds can reject the interface entirely, which
                # is explicitly allowed by libretro.
                if not self.provide_log_interface or not data:
                    return False

                @RetroLogPrintfCallback
                def retro_log(level, msg):
                    # Release frontend: keep Flycast's log interface valid,
                    # but do not spam the screen saver console.
                    return None

                self._log_cb = retro_log
                cb = ctypes.cast(data, POINTER(RetroLogCallback))
                cb[0].log = ctypes.cast(self._log_cb, c_void_p).value
                return True

            if cmd == RETRO_ENVIRONMENT_GET_PERF_INTERFACE:
                if not self.provide_perf_interface or not data:
                    return False

                import time as _time

                @RetroPerfGetTimeUsecCallback
                def get_time_usec():
                    return int(_time.perf_counter_ns() // 1000)

                @RetroPerfGetCpuFeaturesCallback
                def get_cpu_features():
                    # Diagnostic frontend: report no optional SIMD feature bits.
                    return 0

                @RetroPerfGetCounterCallback
                def get_perf_counter():
                    return int(_time.perf_counter_ns())

                @RetroPerfRegisterCallback
                def perf_register(counter):
                    if counter:
                        counter[0].registered = True

                @RetroPerfStartCallback
                def perf_start(counter):
                    if counter:
                        counter[0].start = int(_time.perf_counter_ns())

                @RetroPerfStopCallback
                def perf_stop(counter):
                    if counter:
                        now = int(_time.perf_counter_ns())
                        start = int(counter[0].start)
                        if start:
                            counter[0].total += max(0, now - start)
                            counter[0].call_cnt += 1

                @RetroPerfLogCallback
                def perf_log():
                    return None

                self._perf_get_time_usec_cb = get_time_usec
                self._perf_get_cpu_features_cb = get_cpu_features
                self._perf_get_counter_cb = get_perf_counter
                self._perf_register_cb = perf_register
                self._perf_start_cb = perf_start
                self._perf_stop_cb = perf_stop
                self._perf_log_cb = perf_log

                cb = ctypes.cast(data, POINTER(RetroPerfCallback))
                cb[0].get_time_usec = ctypes.cast(self._perf_get_time_usec_cb, c_void_p).value
                cb[0].get_cpu_features = ctypes.cast(self._perf_get_cpu_features_cb, c_void_p).value
                cb[0].get_perf_counter = ctypes.cast(self._perf_get_counter_cb, c_void_p).value
                cb[0].perf_register = ctypes.cast(self._perf_register_cb, c_void_p).value
                cb[0].perf_start = ctypes.cast(self._perf_start_cb, c_void_p).value
                cb[0].perf_stop = ctypes.cast(self._perf_stop_cb, c_void_p).value
                cb[0].perf_log = ctypes.cast(self._perf_log_cb, c_void_p).value
                return True

            if cmd == RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK:
                # Flycast may provide a keyboard callback. Native Saver has no
                # gameplay keyboard input, but accepting the registration is safe.
                return True

            if cmd == RETRO_ENVIRONMENT_GET_DISK_CONTROL_INTERFACE_VERSION:
                if data:
                    ctypes.cast(data, POINTER(c_uint))[0] = 1
                    return True
                return False

            if cmd in (
                RETRO_ENVIRONMENT_SET_DISK_CONTROL_INTERFACE,
                RETRO_ENVIRONMENT_SET_DISK_CONTROL_EXT_INTERFACE,
            ):
                # Single-disc playback does not need frontend-driven disc swaps.
                # Accept registration so Flycast can continue its normal init path.
                return True

            if cmd == RETRO_ENVIRONMENT_SET_SAVE_STATE_IN_BACKGROUND:
                return True

            if cmd == RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT:
                # This request is normally made during retro_load_game(),
                # before the frontend creates the actual HW context.
                # Record it now and honor it after retro_load_game returns.
                self._hw_shared_requested = True
                print("[hw] shared HW context requested (deferred)", flush=True)
                return True

            if cmd == RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER:
                if self.render_backend == "glcore":
                    ctypes.cast(data, POINTER(c_uint))[0] = RETRO_HW_CONTEXT_OPENGL_CORE
                    print("[hw] preferred libretro HW context=OpenGL Core", flush=True)
                    return True
                if self.render_backend == "opengl":
                    ctypes.cast(data, POINTER(c_uint))[0] = RETRO_HW_CONTEXT_OPENGL
                    print("[hw] preferred libretro HW context=OpenGL", flush=True)
                    return True
                ctypes.cast(data, POINTER(c_uint))[0] = RETRO_HW_CONTEXT_NONE
                return False

            if cmd == RETRO_ENVIRONMENT_SET_HW_RENDER:
                if self.render_backend not in ("opengl", "glcore") or not data:
                    return False

                hw = ctypes.cast(data, POINTER(RetroHWRenderCallback))[0]
                requested = int(hw.context_type)
                if requested not in (
                    RETRO_HW_CONTEXT_OPENGL,
                    RETRO_HW_CONTEXT_OPENGL_CORE,
                ):
                    print(f"[hw] unsupported context request={requested}")
                    return False

                # IMPORTANT: SET_HW_RENDER is called by the core during
                # retro_load_game(). A libretro frontend should accept/register
                # the request here, then create the actual graphics context
                # after retro_load_game() has returned and before context_reset().
                self.hw_context_reset_addr = int(hw.context_reset or 0)
                self.hw_context_destroy_addr = int(hw.context_destroy or 0)
                self._pending_hw_request = {
                    "context_type": requested,
                    "version_major": int(hw.version_major),
                    "version_minor": int(hw.version_minor),
                    "debug_context": bool(hw.debug_context),
                }

                @RetroHWGetCurrentFramebufferCallback
                def get_current_framebuffer():
                    if not self.hw_context:
                        return 0
                    return self.hw_context.framebuffer_id()

                @RetroHWGetProcAddressCallback
                def get_proc_address(sym):
                    if not self.hw_context:
                        return 0
                    return self.hw_context.proc_address(sym)

                self._hw_get_fb_cb = get_current_framebuffer
                self._hw_get_proc_cb = get_proc_address

                hw.get_current_framebuffer = ctypes.cast(
                    self._hw_get_fb_cb, c_void_p
                ).value
                hw.get_proc_address = ctypes.cast(
                    self._hw_get_proc_cb, c_void_p
                ).value

                self.frame_bottom_up = True
                print(
                    f"[hw] SET_HW_RENDER accepted/deferred context={requested} "
                    f"version={int(hw.version_major)}.{int(hw.version_minor)}"
                )
                return True

            if cmd == RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
                fmt = int(ctypes.cast(data, POINTER(c_uint))[0])
                if fmt in (RETRO_PIXEL_FORMAT_0RGB1555, RETRO_PIXEL_FORMAT_XRGB8888, RETRO_PIXEL_FORMAT_RGB565):
                    self.pixel_format = fmt
                    print(f"[libretro] pixel format={fmt}")
                    return True
                return False
            if cmd == RETRO_ENVIRONMENT_SET_VARIABLES:
                ptr = ctypes.cast(data, POINTER(RetroVariable)); i = 0
                if self.trace_core_vars:
                    print("[corevar] SET_VARIABLES begin", flush=True)
                while ptr[i].key:
                    key = decode_cstr(ptr[i].key)
                    raw = decode_cstr(ptr[i].value)

                    from core_options import register_variable
                    register_variable(key, raw, self.variables, self.core_option_overrides, self.trace_core_vars)

                    i += 1

                if self.trace_core_vars:
                    for k, v in sorted(self.core_option_overrides.items()):
                        vv = v.decode("utf-8", errors="replace")
                        present = k in self.variables
                        print(
                            f"[corevar] override-summary key={k} "
                            f"value={vv!r} registered={present}",
                            flush=True,
                        )
                    print("[corevar] SET_VARIABLES end", flush=True)
                return True
            if cmd == RETRO_ENVIRONMENT_GET_VARIABLE:
                if not data:
                    return True

                var_ptr = ctypes.cast(data, POINTER(RetroVariable))
                key = decode_cstr(var_ptr[0].key)

                from core_options import lookup_variable
                val = lookup_variable(key, self.variables, self.core_option_overrides, self.trace_core_vars)

                if val is not None:
                    var_ptr[0].value = val
                else:
                    var_ptr[0].value = None

                return True
            if cmd == RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
                ctypes.cast(data, POINTER(c_bool))[0] = False; return True
            if cmd == RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION:
                ctypes.cast(data, POINTER(c_uint))[0] = 0; return True
            if cmd in (
                RETRO_ENVIRONMENT_SET_CORE_OPTIONS,
                RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL,
            ):
                return False
            if cmd == RETRO_ENVIRONMENT_SET_CORE_OPTIONS_DISPLAY:
                # UI-only hint. Native Saver has no options UI, so accept as no-op.
                return True
            if cmd == RETRO_ENVIRONMENT_SET_GEOMETRY:
                try:
                    geo = ctypes.cast(data, POINTER(RetroGameGeometry))[0]
                    if float(geo.aspect_ratio) > 0:
                        self.display_aspect = float(geo.aspect_ratio)
                except Exception:
                    pass
                return True

            if cmd == RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO:
                try:
                    av = ctypes.cast(data, POINTER(RetroSystemAVInfo))[0]
                    if float(av.geometry.aspect_ratio) > 0:
                        self.display_aspect = float(av.geometry.aspect_ratio)
                except Exception:
                    pass
                return True

            return False

        @VideoRefreshCallback
        def video(data, width, height, pitch):
            w, h = int(width), int(height)

            data_value = int(data or 0)
            if (
                self.hw_context is not None
                and data_value == RETRO_HW_FRAME_BUFFER_VALID
            ):
                # IMPORTANT:
                # Do not touch shared OpenGL state from inside the libretro
                # video callback. Hardware cores such as Dolphin can still be
                # finishing GL work here. Just latch the requested frame size;
                # readback happens after retro_run() has completely returned.
                self._pending_hw_frame = (w, h)
                return

            if not data:
                return

            p = int(pitch)
            self.frame_bottom_up = False

            # v0.4: keep the libretro framebuffer in its native pixel format.
            # For common SNES software formats (0RGB1555/RGB565/XRGB8888),
            # GDI can consume it directly via StretchDIBits + BI_BITFIELDS.
            self.frame_bytes = ctypes.string_at(data, p * h)
            self.frame_w = w
            self.frame_h = h
            self.frame_pitch = p

            if not self._frame_layout_logged:
                bpp = 4 if self.pixel_format == RETRO_PIXEL_FORMAT_XRGB8888 else 2
                row_bytes = w * bpp
                dib_stride = (row_bytes + 3) & ~3
                print(
                    f"[frame] {w}x{h} pixel_format={self.pixel_format} "
                    f"libretro_pitch={p} row_bytes={row_bytes} "
                    f"gdi_stride={dib_stride}"
                )
                self._frame_layout_logged = True

        @AudioSampleCallback
        def audio_sample(l, r):
            return
        @AudioSampleBatchCallback
        def audio_batch(data, frames):
            return frames
        @InputPollCallback
        def input_poll():
            return
        @InputStateCallback
        def input_state(port, device, index, ident):
            if self._startup_input is not None:
                return self._startup_input.state(port, device, index, ident)
            return 0

        self._env = env; self._video = video; self._audio = audio_sample; self._audio_batch = audio_batch
        self._poll = input_poll; self._state = input_state
        self.dll.retro_set_environment(env)
        self.dll.retro_set_video_refresh(video)
        self.dll.retro_set_audio_sample(audio_sample)
        self.dll.retro_set_audio_sample_batch(audio_batch)
        self.dll.retro_set_input_poll(input_poll)
        self.dll.retro_set_input_state(input_state)






