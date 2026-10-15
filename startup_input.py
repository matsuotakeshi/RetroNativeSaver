"""Two short START presses on the emulated first controller only."""


class StartTwice:
    def __init__(self, delay_seconds=5.0):
        self.delay_seconds = delay_seconds
        self.started = None
        self.pressed_at = None
        self.count = 0
        self.down = False

    def advance(self, now):
        if self.started is None:
            self.started = now
        if self.down:
            if now - self.pressed_at >= .1:
                self.down = False
            return False  # Always expose a release frame before another press.
        # Keep the second press a full second after the first even after a stall.
        due = self.started + self.delay_seconds if self.count == 0 else self.pressed_at + 1.0
        if self.count < 2 and now >= due:
            self.down = True
            self.pressed_at = now
            self.count += 1
            return True
        return False

    def state(self, port, device, index, ident):
        if not self.down or port != 0 or (device & 0xff) != 1 or index != 0:
            return 0
        if ident == 256:  # RETRO_DEVICE_ID_JOYPAD_MASK
            return 1 << 3
        return int(ident == 3)  # RETRO_DEVICE_ID_JOYPAD_START
