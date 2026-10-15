"""Supervisor-owned safety state, retained across worker restarts.

The session quarantine remains authoritative even for whitelisted ROMs.
Persistent storage and name matching keep their existing policies.
"""
import datetime
import os
from runtime_policy import watchdog_timeout
from rom_state_store import (_empty_persistent_rom_state, _load_persistent_rom_state,
                             _empty_persistent_rom_whitelist, _load_persistent_rom_whitelist,
                             _record_persistent_rom_failure)
from rom_list_policy import (_persistent_blacklisted_roms, _persistent_whitelisted_roms,
                             _apply_persistent_whitelist, _rom_in_name_map)


class SupervisorSafety:
    """One saver session owns one instance; call load before starting workers."""
    def __init__(self, cfg, resolve_path):
        self.session_rom_quarantine_enabled = bool(
            cfg.get("session_rom_quarantine_enabled", True)
        )

        self.persistent_rom_blacklist_enabled = bool(
            cfg.get("persistent_rom_blacklist_enabled", True)
        )
        self.persistent_rom_blacklist_threshold_sessions = max(
            2,
            int(cfg.get(
                "persistent_rom_blacklist_threshold_sessions",
                2,
            )),
        )
        self.persistent_rom_blacklist_path = resolve_path(
            cfg.get("persistent_rom_blacklist_file"),
            r"state\persistent_rom_blacklist.json",
        )

        self.persistent_rom_whitelist_enabled = bool(
            cfg.get("persistent_rom_whitelist_enabled", True)
        )
        self.persistent_rom_whitelist_path = resolve_path(
            cfg.get("persistent_rom_whitelist_file"),
            r"state\persistent_rom_whitelist.json",
        )
        self.persistent_rom_whitelist_seed_path = resolve_path(
            cfg.get("persistent_rom_whitelist_seed_file"),
            "persistent_rom_whitelist.default.json",
        )

        self.persistent_session_id = (
            datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
            + f"-pid{os.getpid()}"
        )

        self.session_system_crash_limit = max(
            1,
            int(cfg.get("session_system_crash_limit", 3)),
        )

        # Native cores can occasionally hang inside retro_run() without crashing.
        # A hung process still satisfies proc.poll() is None, so the supervisor
        # must also watch the shared-memory native-call trace for forward progress.
        # Log the exact thresholds used by the monitor, not a separately clamped copy.
        self.worker_run_hang_timeout_seconds = watchdog_timeout('RUN_ENTER', cfg)
        self.worker_start_hang_timeout_seconds = watchdog_timeout('START_ENTER', cfg)
        self.worker_watchdog_poll_seconds = max(
            0.05,
            float(cfg.get(
                "worker_watchdog_poll_seconds",
                0.25,
            )),
        )


    def load(self):
        self.persistent_rom_state = _empty_persistent_rom_state()
        persistent_blacklisted = {}

        if self.persistent_rom_blacklist_enabled:
            self.persistent_rom_state = _load_persistent_rom_state(
                self.persistent_rom_blacklist_path
            )
            persistent_blacklisted = _persistent_blacklisted_roms(
                self.persistent_rom_state
            )

        persistent_rom_whitelist_state = (
            _empty_persistent_rom_whitelist()
        )
        self.persistent_whitelisted = {}
        if self.persistent_rom_whitelist_enabled:
            persistent_rom_whitelist_state = (
                _load_persistent_rom_whitelist(
                    self.persistent_rom_whitelist_path,
                    self.persistent_rom_whitelist_seed_path,
                )
            )
            self.persistent_whitelisted = _persistent_whitelisted_roms(
                persistent_rom_whitelist_state
            )

        effective_persistent_blacklisted, whitelist_rescued = (
            _apply_persistent_whitelist(
                persistent_blacklisted,
                self.persistent_whitelisted,
            )
        )

        # Only failures in this saver session belong here. Workers separately
        # filter persistent exclusions for ordinary picks, so favorites can
        # bypass those exclusions without bypassing an actual session failure.
        self.session_quarantine = {}
        self.session_crash_counts = {}
        self.session_disabled_systems = set()

        persistent_blacklist_total = sum(
            len(names)
            for names in persistent_blacklisted.values()
        )
        effective_blacklist_total = sum(
            len(names)
            for names in effective_persistent_blacklisted.values()
        )
        persistent_whitelist_total = sum(
            len(names)
            for names in self.persistent_whitelisted.values()
        )

        print(
            "[persistent-safety] policy: "
            f"enabled={'yes' if self.persistent_rom_blacklist_enabled else 'no'} "
            f"threshold={self.persistent_rom_blacklist_threshold_sessions} "
            f"session_id={self.persistent_session_id} "
            f"file={self.persistent_rom_blacklist_path}",
            flush=True,
        )
        print(
            "[persistent-safety] whitelist policy: "
            f"enabled={'yes' if self.persistent_rom_whitelist_enabled else 'no'} "
            f"file={self.persistent_rom_whitelist_path}",
            flush=True,
        )
        print(
            "[persistent-safety] loaded "
            f"{persistent_blacklist_total} blacklisted ROM(s), "
            f"{persistent_whitelist_total} whitelisted ROM(s), "
            f"rescued={whitelist_rescued}, "
            f"effective_blacklist={effective_blacklist_total}",
            flush=True,
        )

        print(
            "[session-safety] supervisor policy: "
            f"rom_quarantine={'on' if self.session_rom_quarantine_enabled else 'off'} "
            f"system_crash_limit={self.session_system_crash_limit}",
            flush=True,
        )
        print(
            "[watchdog] supervisor policy: "
            f"run_hang_timeout={self.worker_run_hang_timeout_seconds:.1f}s "
            f"start_hang_timeout={self.worker_start_hang_timeout_seconds:.1f}s "
            f"poll={self.worker_watchdog_poll_seconds:.2f}s",
            flush=True,
        )

        return self.persistent_rom_state, self.persistent_whitelisted, self.session_quarantine, self.session_crash_counts, self.session_disabled_systems


    def record_runtime_failure(self, snapshot, watchdog_triggered):
        crash_system = str(snapshot.get("system", "")).strip()
        crash_rom = str(snapshot.get("rom", "")).strip()
        crash_phase = str(snapshot.get("phase", "")).strip()
        failure_kind = (
            "hang" if watchdog_triggered else "crash"
        )

        if crash_system:
            new_count = (
                self.session_crash_counts.get(crash_system, 0) + 1
            )
            self.session_crash_counts[crash_system] = new_count

            print(
                f"[session-safety] {failure_kind} "
                f"[{crash_system}] count={new_count}/"
                f"{self.session_system_crash_limit} "
                f"phase={crash_phase}",
                flush=True,
            )

            if (
                self.session_rom_quarantine_enabled
                and crash_rom
            ):
                bucket = self.session_quarantine.setdefault(
                    crash_system,
                    set(),
                )
                if crash_rom not in bucket:
                    bucket.add(crash_rom)
                    print(
                        f"[session-safety] ROM quarantined "
                        f"[{crash_system}] {crash_rom}",
                        flush=True,
                    )

            rom_is_whitelisted = (
                self.persistent_rom_whitelist_enabled
                and crash_rom
                and _rom_in_name_map(
                    self.persistent_whitelisted,
                    crash_system,
                    crash_rom,
                )
            )

            if rom_is_whitelisted:
                print(
                    f"[persistent-safety] WHITELIST protects "
                    f"[{crash_system}] {crash_rom}; "
                    "persistent failure evidence unchanged "
                    "(session quarantine still applies)",
                    flush=True,
                )
            elif (
                self.persistent_rom_blacklist_enabled
                and crash_rom
            ):
                (
                    persistent_failures,
                    newly_blacklisted,
                    already_recorded,
                ) = _record_persistent_rom_failure(
                    self.persistent_rom_state,
                    self.persistent_rom_blacklist_path,
                    self.persistent_session_id,
                    self.persistent_rom_blacklist_threshold_sessions,
                    crash_system,
                    crash_rom,
                    crash_phase,
                    failure_kind,
                )

                if already_recorded:
                    print(
                        f"[persistent-safety] evidence already "
                        f"recorded this session "
                        f"[{crash_system}] {crash_rom} "
                        f"sessions={persistent_failures}/"
                        f"{self.persistent_rom_blacklist_threshold_sessions}",
                        flush=True,
                    )
                elif newly_blacklisted:
                    print(
                        f"[persistent-safety] ROM BLACKLISTED "
                        f"[{crash_system}] {crash_rom} "
                        f"after {persistent_failures} separate "
                        "screen-saver sessions",
                        flush=True,
                    )
                else:
                    print(
                        f"[persistent-safety] failure evidence "
                        f"[{crash_system}] {crash_rom} "
                        f"sessions={persistent_failures}/"
                        f"{self.persistent_rom_blacklist_threshold_sessions}; "
                        "ROM will be retried next screen-saver session",
                        flush=True,
                    )

            if (
                new_count >= self.session_system_crash_limit
                and crash_system not in self.session_disabled_systems
            ):
                self.session_disabled_systems.add(crash_system)
                print(
                    f"[session-safety] SYSTEM SUSPENDED "
                    f"[{crash_system}] after {new_count} "
                    "runtime/startup crash/hang event(s); it will return "
                    "next time the screen saver starts",
                    flush=True,
                )

