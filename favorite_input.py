"""Per-ROM automatic libretro input; never sends Windows input messages."""
import ctypes
import math

BUTTONS = {'B':0, 'Y':1, 'Select':2, 'Start':3, 'Up':4, 'Down':5,
           'Left':6, 'Right':7, 'A':8, 'X':9, 'L':10, 'R':11,
           'L2':12, 'R2':13, 'L3':14, 'R3':15}
# libretro.h retro_key values. UI labels are independent of Windows key codes.
KEYBOARD = {'Backspace': 8,
 'Tab': 9,
 'Clear': 12,
 'Enter': 13,
 'Pause': 19,
 'Escape': 27,
 'Space': 32,
 'Exclaim': 33,
 'Quotedbl': 34,
 'Hash': 35,
 'Dollar': 36,
 'Ampersand': 38,
 'Quote': 39,
 'Leftparen': 40,
 'Rightparen': 41,
 'Asterisk': 42,
 'Plus': 43,
 'Comma': 44,
 'Minus': 45,
 'Period': 46,
 'Slash': 47,
 '0': 48,
 '1': 49,
 '2': 50,
 '3': 51,
 '4': 52,
 '5': 53,
 '6': 54,
 '7': 55,
 '8': 56,
 '9': 57,
 'Colon': 58,
 'Semicolon': 59,
 'Less': 60,
 'Equals': 61,
 'Greater': 62,
 'Question': 63,
 'At': 64,
 'Leftbracket': 91,
 'Backslash': 92,
 'Rightbracket': 93,
 'Caret': 94,
 'Underscore': 95,
 'Backquote': 96,
 'A': 97,
 'B': 98,
 'C': 99,
 'D': 100,
 'E': 101,
 'F': 102,
 'G': 103,
 'H': 104,
 'I': 105,
 'J': 106,
 'K': 107,
 'L': 108,
 'M': 109,
 'N': 110,
 'O': 111,
 'P': 112,
 'Q': 113,
 'R': 114,
 'S': 115,
 'T': 116,
 'U': 117,
 'V': 118,
 'W': 119,
 'X': 120,
 'Y': 121,
 'Z': 122,
 'Leftbrace': 123,
 'Bar': 124,
 'Rightbrace': 125,
 'Tilde': 126,
 'Delete': 127,
 'Kp0': 256,
 'Kp1': 257,
 'Kp2': 258,
 'Kp3': 259,
 'Kp4': 260,
 'Kp5': 261,
 'Kp6': 262,
 'Kp7': 263,
 'Kp8': 264,
 'Kp9': 265,
 'Kp Period': 266,
 'Kp Divide': 267,
 'Kp Multiply': 268,
 'Kp Minus': 269,
 'Kp Plus': 270,
 'Kp Enter': 271,
 'Kp Equals': 272,
 'Up': 273,
 'Down': 274,
 'Right': 275,
 'Left': 276,
 'Insert': 277,
 'Home': 278,
 'End': 279,
 'Pageup': 280,
 'Pagedown': 281,
 'F1': 282,
 'F2': 283,
 'F3': 284,
 'F4': 285,
 'F5': 286,
 'F6': 287,
 'F7': 288,
 'F8': 289,
 'F9': 290,
 'F10': 291,
 'F11': 292,
 'F12': 293,
 'F13': 294,
 'F14': 295,
 'F15': 296,
 'Numlock': 300,
 'Capslock': 301,
 'Scrollock': 302,
 'Rshift': 303,
 'Lshift': 304,
 'Rctrl': 305,
 'Lctrl': 306,
 'Ralt': 307,
 'Lalt': 308,
 'Rmeta': 309,
 'Lmeta': 310,
 'Lsuper': 311,
 'Rsuper': 312,
 'Mode': 313,
 'Compose': 314,
 'Help': 315,
 'Print': 316,
 'Sysreq': 317,
 'Break': 318,
 'Menu': 319,
 'Power': 320,
 'Euro': 321,
 'Undo': 322,
 'Oem 102': 323}
KEYS = {'joypad': BUTTONS, 'keyboard': KEYBOARD}
KeyboardEvent = ctypes.CFUNCTYPE(None, ctypes.c_bool, ctypes.c_uint,
                                ctypes.c_uint32, ctypes.c_uint16)


def validate_input(value):
    if isinstance(value, list):
        if not value or any(not isinstance(step, dict) for step in value):
            raise ValueError('連続入力には1つ以上の入力を指定してください。')
        steps = [validate_input(step) for step in value]
        if any(b['delay_seconds'] < a['delay_seconds'] for a, b in zip(steps, steps[1:])):
            raise ValueError('入力は開始からの秒数が小さい順に並べてください。')
        return steps
    if not isinstance(value, dict):
        raise ValueError('自動入力は秒数・入力種類・キーを指定してください。')
    delay = value.get('delay_seconds')
    if isinstance(delay, bool) or not isinstance(delay, (int, float)):
        raise ValueError('入力までの秒数は0以上の有限の数値にしてください。')
    try:
        delay = float(delay)
    except OverflowError:
        raise ValueError('入力までの秒数は0以上の有限の数値にしてください。') from None
    if not math.isfinite(delay) or delay < 0:
        raise ValueError('入力までの秒数は0以上の有限の数値にしてください。')
    device = value.get('device')
    key = value.get('key')
    if not isinstance(device, str) or device not in KEYS or not isinstance(key, str) or key not in KEYS[device]:
        raise ValueError('入力種類とキーを一覧から選択してください。')
    return dict(delay_seconds=delay, device=device, key=key)


def input_summary(value):
    if value is None:
        return '設定なし'
    value = validate_input(value)
    if isinstance(value, list):
        return ' → '.join(input_summary(step) for step in value)
    kind = 'ボタン' if value['device'] == 'joypad' else 'キー'
    return f"{value['delay_seconds']:g}秒後 / {kind}: {value['key']}"


def system_for_favorite_rom(system, rom, favorites):
    """Return a ROM-scoped copy; never alter a machine's shared definition."""
    for candidate, path in favorites or ():
        if candidate['id'] == system['id'] and path == rom and '_favorite_startup_input' in candidate:
            return dict(system, _favorite_startup_input=validate_input(candidate['_favorite_startup_input']))
    if '_favorite_startup_input' in system:
        clean = dict(system)
        clean.pop('_favorite_startup_input')
        return clean
    return system


def register_keyboard_callback(core, data):
    # Copy the address, not a pointer to the core's potentially temporary struct.
    address = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0] if data else None
    core._keyboard_event = KeyboardEvent(address) if address else None
    return True


class FavoritePress:
    favorite = True

    def __init__(self, value):
        value = validate_input(value)
        self.steps = value if isinstance(value, list) else [value]
        self.config = self.steps[0]
        self.ident = KEYS[self.config['device']][self.config['key']]
        self.started = self.pressed_at = None
        self.down = False
        self.count = 0
        self.pending = None

    def advance(self, now):
        if self.started is None:
            self.started = now
        if self.down:
            if now - self.pressed_at >= .1:
                self.down = False
                self.pending = False
            return False
        if self.count < len(self.steps) and now >= self.started + self.steps[self.count]['delay_seconds']:
            self.config = self.steps[self.count]
            self.ident = KEYS[self.config['device']][self.config['key']]
            self.down = True
            self.pending = True
            self.pressed_at = now
            self.count += 1
            return True
        return False

    def state(self, port, device, index, ident):
        expected = 1 if self.config['device'] == 'joypad' else 3
        if not self.down or port != 0 or (device & 0xff) != expected or index != 0:
            return 0
        if expected == 1 and ident == 256:
            return ctypes.c_int16(1 << self.ident).value
        return int(ident == self.ident)

    def dispatch_keyboard(self, callback):
        if self.pending is None:
            return
        down, self.pending = self.pending, None
        if self.config['device'] != 'keyboard' or callback is None:
            return
        # Printable single key only; modifiers/combos are not synthesized.
        character = self.ident if down and (self.ident in (8, 9, 13, 27) or 32 <= self.ident <= 126) else 0
        modifiers = {303:1, 304:1, 305:2, 306:2, 307:4, 308:4,
                     309:8, 310:8, 311:8, 312:8}.get(self.ident, 0) if down else 0
        callback(down, self.ident, character, modifiers)
