"""Diagnostic stream and trace records; caller owns log files and memory mappings."""
import datetime
import os
import sys

RUNTIME_TRACE_SIZE = 8192


class _DiagnosticStream:
    def __init__(self, original, logfile, channel):
        self.original = original
        self.logfile = logfile
        self.channel = channel
        self._line_start = True

    def write(self, value):
        if value is None:
            return 0
        text_value = str(value)
        if not text_value:
            return 0

        pieces = text_value.splitlines(True)
        for piece in pieces:
            if self._line_start:
                role = ("supervisor-guard" if "--supervisor-guard" in sys.argv[1:]
                        else "slot-worker" if "--slot-worker" in sys.argv[1:]
                        else "worker" if "--worker" in sys.argv[1:] else "supervisor")
                stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                prefix = f"{stamp} pid={os.getpid()} {role} {self.channel} "
            else:
                prefix = ""

            payload = prefix + piece
            try:
                self.logfile.write(payload)
            except Exception:
                pass
            if self.original is not None:
                try:
                    self.original.write(payload)
                except Exception:
                    pass

            self._line_start = piece.endswith("\n") or piece.endswith("\r")

        return len(text_value)

    def flush(self):
        try:
            self.logfile.flush()
        except Exception:
            pass
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass

    def isatty(self):
        if self.original is None:
            return False
        try:
            return bool(self.original.isatty())
        except Exception:
            return False

    @property
    def encoding(self):
        if self.original is not None:
            return getattr(self.original, "encoding", "utf-8")
        return "utf-8"


def _runtime_trace_clean(value) -> str:
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def write_runtime_trace(
    mm,
    phase,
    cycle=0,
    slot=0,
    system="",
    rom="",
    loop_count=0,
    call_count=0,
):
    """
    Store one fixed-size "where am I right now?" record in shared memory.

    No flush() is needed: this is a shared-memory mapping, not a disk-backed
    logfile. The supervisor reads it only after the worker has exited.
    """
    if mm is None:
        return

    record = (
        f"{_runtime_trace_clean(phase)}\t"
        f"{int(cycle)}\t"
        f"{int(slot)}\t"
        f"{_runtime_trace_clean(system)}\t"
        f"{_runtime_trace_clean(rom)}\t"
        f"{int(loop_count)}\t"
        f"{int(call_count)}"
    ).encode("utf-8", errors="replace")

    if len(record) >= RUNTIME_TRACE_SIZE:
        record = record[:RUNTIME_TRACE_SIZE - 1]

    try:
        mm.seek(0)
        mm.write(record)
        mm.write(b"\0")
    except Exception:
        # Runtime tracing must never be able to take down the screen saver.
        pass


def read_runtime_trace(mm):
    if mm is None:
        return None

    try:
        mm.seek(0)
        raw = mm.read(RUNTIME_TRACE_SIZE)
    except Exception as exc:
        return {
            "phase": "READ_ERROR",
            "cycle": 0,
            "slot": 0,
            "system": "",
            "rom": "",
            "loop_count": 0,
            "call_count": 0,
            "raw": str(exc),
        }

    raw = raw.split(b"\0", 1)[0]
    if not raw:
        return None

    decoded = raw.decode("utf-8", errors="replace")
    parts = decoded.split("\t", 6)
    while len(parts) < 7:
        parts.append("")

    phase, cycle, slot, system, rom, loop_count, call_count = parts

    def _to_int(value):
        try:
            return int(value)
        except Exception:
            return 0

    return {
        "phase": phase,
        "cycle": _to_int(cycle),
        "slot": _to_int(slot),
        "system": system,
        "rom": rom,
        "loop_count": _to_int(loop_count),
        "call_count": _to_int(call_count),
        "raw": decoded,
    }


def log_runtime_trace_snapshot(mm, worker_pid, reason):
    snapshot = read_runtime_trace(mm)
    if not snapshot:
        print(
            f"[runtime-trace] worker pid={worker_pid} "
            f"reason={reason} no trace record",
            flush=True,
        )
        return None

    print(
        f"[runtime-trace] worker pid={worker_pid} reason={reason} "
        f"last phase={snapshot['phase']} "
        f"cycle={snapshot['cycle']} "
        f"slot={snapshot['slot']} "
        f"[{snapshot['system']}] {snapshot['rom']} "
        f"loop={snapshot['loop_count']} "
        f"call={snapshot['call_count']}",
        flush=True,
    )
    return snapshot
