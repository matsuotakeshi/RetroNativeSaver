"""Existing libretro ABI definitions and DLL signatures; no runtime ownership."""
import ctypes
from ctypes import (CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_double, c_float, c_int16, c_int64, c_size_t, c_uint, c_uint64, c_void_p, c_int)

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


def bind_api(d):
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
