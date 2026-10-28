[日本語](README.ja.md) | English

# RetroNativeSaver

A Windows screensaver that displays multiple games in a tiled layout. Each tile runs a libretro core in its own child process. Grouped mode supports **up to 64 simultaneous game displays across multiple monitors**. Current version: **v0.22.3**.

The project is licensed under **GNU GPL v3 (GPL-3.0-only)**. Third-party code, including X1/libretro components, retains its [own licenses](THIRD_PARTY_NOTICES.md).

## Features

- Multiple monitors, with independent ROM selection, fades, and rotation timing for each tile.
- A favorites tile in the upper-left corner, with configurable sequences of game-button and keyboard inputs for each favorite.
- Concurrent execution limits using `resource_group` and `resource_weight`.
- Blacklist and whitelist management, with retries when a ROM fails to start.
- A choice between normal and grouped layouts, drawn randomly at startup. Grouped mode fills up to 64 tiles with games from the selected system group.
- Multi-disk preparation for systems such as PC-88, PC-98, X1, and X68000. See `systems.example/` for supported systems and example core settings.

## Supported Systems

RetroNativeSaver includes example configurations for **38 systems**, covering home consoles, handhelds, arcade hardware, and classic Japanese computers.

| Category          | Systems                                                                                                                                 |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Nintendo          | NES, Famicom Disk System (FDS), SNES, Nintendo 64, Game Boy, Game Boy Color, Game Boy Advance, Nintendo DS, Nintendo 3DS, GameCube, Wii |
| Sega              | SG-1000, Master System, Game Gear, Mega Drive / Genesis, Mega-CD / Sega CD, Saturn, Dreamcast                                           |
| NEC               | PC Engine / TurboGrafx-16, PC Engine CD-ROM², PC-FX                                                                                     |
| Sony              | PlayStation, PlayStation 2, PSP                                                                                                         |
| SNK               | Neo Geo CD, Neo Geo Pocket, Neo Geo Pocket Color                                                                                        |
| Bandai            | WonderSwan, WonderSwan Color                                                                                                            |
| Other Consoles    | 3DO                                                                                                                                     |
| Arcade            | FinalBurn Neo (FBNeo), MAME                                                                                                             |
| Classic Computers | MSX, PC-8801, PC-9801, Sharp X1, Sharp X68000, FM-7 (experimental)                                                                      |

**Compatibility notes**

- Each system requires a compatible libretro core, and some require additional BIOS files.
- Performance and compatibility vary by core, game, and hardware.
- Not all systems can run in 64-tile grouped mode.
- FBNeo grouped mode is disabled by default because of its memory requirements.
- Nintendo 64 can be resource-intensive, particularly when running multiple instances.

Configuration examples are available in `systems.example/`. Inclusion in this list does not guarantee compatibility with every game or system configuration.

## Emulating up to 64 games at once

Each tile has an independent child process that loads a libretro core and a ROM, runs the game, and draws its frames in that tile. A 64-tile layout uses 64 game processes. The scheduler handles ROM selection, startup, monitoring, and replacement. It limits concurrent initialization and displays each tile as it becomes ready.

At startup, grouped mode randomly selects one group, such as Mega Drive + Mega-CD or GB + GBC + GBA, and keeps that group until an explicit Up-key redraw. Each tile selects its own ROM, filling the screens with games from the same group, each progressing independently. See "Grouped mode" below for the available groups and the selection ratio between normal and grouped modes.

To reduce rendering overhead, grouped mode limits each tile's display updates to 25 fps by default. Emulation runs at the rate specified by the core, with display updates scheduled separately. Actual performance and CPU and memory requirements depend on the systems, ROMs, and PC hardware.

## Multiple-monitor layouts

With `multi_monitor` set to `true` in `config.json`, fullscreen mode reads the Windows monitor arrangement and places tiles on each monitor. Monitors with different resolutions can be combined, and each game's image fits within its tile while preserving its aspect ratio.

In grouped mode, the following two-monitor setup provides 64 tiles:

| Monitor resolution | Grid (columns × rows) | Tiles |
|---|---|---|
| 1920×1080 | 7×4 | 28 |
| 2560×1080 | 9×4 | 36 |
| **Total** | | **64** |

The tile count is determined by each monitor's resolution. Grouped mode normally uses a 7×4 grid for resolutions other than 2560×1080. The FBNeo-only group uses 4×4 tiles per monitor to reduce load, for a total of 32 tiles on two monitors. If the monitor arrangement would exceed the grouped-mode tile limit, the screensaver falls back to normal mode. Normal mode chooses its tile count based on resolution and `max_slots_per_monitor`.

## Independent, asynchronous rotation

The default configuration enables `independent_slots_enabled`, giving each tile its own display duration. When a tile's time expires, it fades out, loads the next ROM, and fades back in while the other tiles continue running. This gradually changes different parts of the screens in both normal and grouped modes.

Each tile's duration is drawn anew around `cycle_seconds`, with a random variation of up to `independent_jitter_seconds` in either direction. The shared settings in the sample configuration are **150 seconds ±15 seconds (135–165 seconds)**. Setting the same keys in `systems/<system-id>.json` overrides the shared values for that system, so systems that take longer to start can stay on screen longer.

Timing begins when the first video frame is received from each core. Differences in startup times and durations spread out tile replacements. Adjust `fade_duration_ms` to change the fade duration. To replace games immediately, press Up to redraw the mode and group and replace all tiles, or Down to replace only the favorites tile.

## Requirements

Windows x64, Python, PyInstaller, and the libretro cores, ROMs, and any required BIOS files for your systems. The development environment uses Python 3.14. ROMs, BIOS files, personal saves, favorites, and ROM catalogs are not included in this repository.

## Installation folder and write permissions

**Place the entire application folder in a location writable by the Windows account that runs the screensaver**, such as `%LOCALAPPDATA%\RetroNativeSaver`.

When enabled, runtime logs are written to `logs/` beside the EXE/SCR; logging is off by default. The application also writes favorites and files under `state/`, such as the ROM catalog and blacklist/whitelist. Any configured save directories must be writable as well.

Avoid protected locations such as `Program Files` and `C:\Windows\System32`. Keep the EXE/SCR, `_internal`, and the other accompanying files together, then run `install_saver.bat` from that folder to register the screensaver with Windows.

## Setup and build

```powershell
python -m pip install -r requirements.txt
python initialize_config.py
```

Initialization creates `config.json`, `favorites.json`, `systems/`, and an empty whitelist. Existing files are preserved. Update the sample `C:/ROMs/<system-id>`, `C:/RetroArch-win64/cores`, and BIOS paths to match your environment. Set `enabled` to `false` for systems you do not use.

```powershell
.\build.bat
```

The build creates the executable, SCR file, and supporting files in `dist/RetroNativeSaver/`. Keep the entire folder together when deploying it. The build also initializes any missing configuration files.

1. Run `dist/RetroNativeSaver/update_rom_catalog.bat` to create the fixed ROM catalog.
2. Run `test_saver.bat` to check the display.
3. Run `install_saver.bat` to register the screensaver, then check the Windows screensaver settings.

After adding or moving ROMs, manually update the catalog with `update_rom_catalog.bat`. When updating an existing installation, preserve its configuration, `save`, `state`, and favorites.

X1 support uses a custom core build for two drives. The DLL is not included in Git. Follow the [build instructions](cores/X1_BUILD.md) to prepare `cores/x1_rns_libretro.dll`. Other systems use externally supplied libretro cores.

For PC-98, X1, X68000 and FM-7 with `disk_boot_mode: "computer_two_drives"`, `Disk 1 of N` / `Disk 2 of N` take priority over a secondary disk label. Without that notation, `Disk 1` / `Disk 2` or `Disk A` / `Disk B` select drives 1 and 2. Recognized role notes such as `(System)` and `(Disk 1)` are ignored when matching an explicitly numbered set; edition and dump annotations remain part of the match. An ambiguous set or a missing boot disk is rejected.

## Controls

| Input | Action |
|---|---|
| Left / Right | Select a tile. The selection indicator disappears after a period without selection input |
| Insert | Add the selected game to favorites |
| Delete | Add a game in a normal tile to the blacklist, or remove a game in the favorites tile from favorites. Replace that tile |
| Up | Redraw normal/grouped mode and the group, then replace all tiles |
| Down | Replace only the favorites tile |
| Enter | Exit the screensaver and launch the selected game in RetroArch |
| PageUp / PageDown | Increase / decrease tile rows on all displays and save the setting |
| Mouse movement / wheel / buttons / touch / other exit keys | Exit the screensaver |

If Enter is used from a separate screensaver desktop, the launcher looks up the normal Windows desktop on a dedicated thread. It preserves the saver process cleanup and launches RetroArch outside the saver Job. It does not switch desktops or unlock Windows; a locked or authentication-required desktop still prevents this fallback.

Use `configure_favorites.bat` to edit favorites and their startup input sequences. Use `configure_rom_lists.bat` to manage ROM lists.

On-screen labels display `System / Game` on one line at the upper left of each tile, scrolling from right to left and repeating within that tile. Both parts use the system-label font and `overlay.system_font_size`; their existing colors are retained. Core suffixes used by the example configurations are omitted on screen, while configured names remain unchanged in logs.

Scrolling is enabled by default, including when updating an existing configuration. The `overlay` settings `scroll_speed` (pixels/second, default 24), `scroll_pause_seconds` (pause at the left edge, default 2) and `scroll_gap` (minimum pixels between repeats, default 48) control its motion. Short labels also scroll. Set `scroll_speed` to `0` for a stationary single line, or `scroll_enabled` to `false` to restore the two-line display with `game_font_size` and `line_gap`. Keyboard selection/help messages remain stationary. Settings, saves, favorites and ROM selection are otherwise unchanged.

## Settings dialog

**General → Tile rows** controls both normal and grouped fullscreen layouts. `tile_rows: 0` (the default, including when absent) retains the previous automatic layouts until PageUp or PageDown is used. `1` means one fullscreen tile per display. From `2` upward, each display's width/height ratio determines its columns, producing approximately square cells while the game keeps its own aspect ratio. For example, four rows give 7×4 tiles at 1920×1080 and 9×4 at 2560×1080.

Cells are at least 270 physical pixels high (the existing 1080-pixel, four-row grid), unless the entire display is smaller. Requested rows are reduced as necessary for display resolution and the 64-tile total limit (32 for the FBNeo-only group). The old `max_slots_per_monitor` option applies only to the legacy normal layout; machine concurrency and resource-weight limits still apply to the new normal layout. Some cells can remain empty when those limits prevent additional games.

With `tile_resize_keys_enabled: true` (default), PageUp increases rows and PageDown decreases rows on all displays together. Each press changes one row; held-key auto-repeat is ignored. Rapid presses are combined for saving, then only `tile_rows` is merged into the latest JSON with backup and atomic replacement. A save failure keeps the current layout and is reported in the optional log. With asynchronous tiles, surviving games continue, excess processes are safely stopped, and added cells start normally. Synchronous mode starts a new cycle using its existing safe cleanup/recycle path. Preview, windowed tests, and explicit `--slots` commands keep their original layout and wheel-to-exit behavior. The mouse wheel always exits the saver. Setting `tile_resize_keys_enabled: false` makes PageUp/PageDown exit too. The old v0.22.1 `tile_wheel_enabled` value is only a fallback for the new enable/disable setting; it never assigns the wheel.

Open **Settings** in the Windows screensaver dialog, use RandomSaver's configuration command, or run `configure_saver.bat`. The EXE/SCR accepts `/c`, `/c:HWND`, or `/c HWND`; an optional `--config <path>` selects another existing configuration file.

**General → Language / 言語** selects **Automatic (Windows)**, **English**, or **日本語**. Automatic is the default, including when `ui_language` is absent: Japanese for a Japanese Windows display language, English otherwise. Save with Apply / OK and reopen the window. Favorites, startup input, ROM selection, blacklist/whitelist, and application messages use the same saved preference. JSON stores `ui_language` as `auto`, `en`, or `ja`; game titles, user-defined names and paths are preserved. Windows file pickers, standard button captions and OS error details may follow the Windows language.

- **General**: monitors, shared rotation time and random variation, asynchronous display, frame-rate cap, fades, keyboard controls, and log output.
- **Title display**: one-line scrolling, font sizes, colors, spacing, and background opacity.
- **Grouped display**: enable/disable grouped selection, normal/grouped weights, frame-rate cap, and included systems within the existing groups. Group membership and resource limits remain in JSON.
- Buttons open the existing favorites/input editor and blacklist/whitelist editor, or update the ROM catalog without launching emulators.

**OK** saves and closes; **Apply** saves; **Cancel** discards unsaved dialog edits. Settings take effect on the next saver launch. Management tools use the saved configuration and save their own changes independently; Cancel does not undo those changes. ROM catalog updates must finish before closing the settings dialog.

The dialog updates only edited settings in `config.json`, preserving unknown keys, explicit group definitions, legacy options, and per-system files. Opening or applying an unchanged dialog does not rewrite the file. On save, the original file is backed up as `config.json.bak-...`, then replaced atomically; JSON formatting may change. A malformed file or a file changed externally is not overwritten. The dialog requires an existing config; it does not silently initialize defaults on errors.

**Application logging is off by default**, including for existing configurations without the new `log_output_enabled` key. Enable **General → Log output** (Japanese UI: `全般 → ログを出力する`) or set `"log_output_enabled": true` to restore the daily logs in `logs/`. Supervisor, worker, tile-worker, and watchdog logs share the same session choice. Turning logging off does not remove old logs, disable in-memory monitoring, or change cleanup, saves, favorites, or ROM-list state. Explicit measurement runs with `RNS_STARTUP_TIMING=1` still create their requested startup traces. Files written independently by a libretro core are outside this application-log setting.

### System-specific settings and RetroArch

The **System settings** tab (Japanese UI: `機種別`) has a system selector populated from the configured `systems_dir`, including disabled systems. Select a system to edit its enabled state, name, core DLL, ROM/BIOS/save/assets folders, rotation time, concurrency/resource settings, renderer, ROM scanning and disk startup options, compatibility flags, title metadata, and core options. Core-option names and values are entered manually; opening the dialog does not load a core. System IDs and unedited or unknown JSON fields are preserved. Invalid files appear as errors without blocking the other systems.

Edits are retained while switching systems. **Apply/OK** saves the common configuration and every edited system file; switching systems alone never saves. For optional per-system values, **Use shared/default** (`共通／既定を使用`) removes the local key so the existing runtime fallback applies. A system's temporary-save option still takes precedence over its save-folder setting. In grouped mode, the existing grouped capacity rules still override normal per-system concurrency. After changing ROM folders, extensions or other scan conditions, save and use **Update ROM catalog**; a reminder is shown. Saving settings is blocked while that update is running.

All edited documents are validated and checked for external changes before writing starts. Each file is backed up and atomically replaced individually. If a later write fails, the dialog identifies the files already saved and retains the remaining edits for retry; this is not an all-files transaction. Cancel discards only edits that have not been saved.

**General → RetroArch EXE** lets you browse for the executable used when pressing Enter on a selected game. It writes the existing `retroarch_path` key in `config.json`. Previously this option was available only in JSON. An empty value retains the existing search order: `retroarch.exe` above the selected core's `cores` directory, then beside the effective BIOS `system` directory. An explicit path takes precedence and never silently falls back to another executable. The handoff and emulator startup mechanisms are unchanged.

## Grouped mode

The default selection ratio is 50% normal mode / 50% grouped mode. Adjust the ratio using `single_system_mode.normal_weight` and `grouped_weight`. One group is selected at startup. Automatic ROM replacements stay within that group. Pressing Up repeats the mode lottery using the configured ratio and, if grouped mode wins, selects a group again. The same mode/group may be drawn again. Saved tile rows, favorites, resource limits, and current-session failure exclusions are retained. Explicit diagnostic commands (`--presentation`, `--system`, `--slots`, windowed mode) keep their restrictions; standalone `--worker` retains ROM-only replacement.

```json
[
  ["megadrive", "megacd"],
  ["pcengine", "pcenginecd", "pcfx"],
  ["gb", "gbc", "gba"],
  ["fds", "nes"],
  ["snes"],
  ["fbneo"],
  ["msx", "x1", "x68000", "pc88", "pc98"],
  ["neocd"]
]
```

Systems listed in `single_system_mode.disabled_systems` are excluded from grouped mode. The sample uses `["fbneo"]` to disable FBNeo in grouped mode; set it to `[]` to enable it again. This does not affect system settings for normal mode. The display update limit is the lower of `single_system_mode.max_fps` and the shared `independent_max_fps` setting. The default is 25 fps.

The PC Engine / CD-ROM² group also supports PC-FX. For an existing explicit group list, add `"pcfx"` to the same group, or run `enable_pcfx_group.bat` from the installation folder after updating to v0.21.23 or later. The batch backs up `config.json` and preserves other setting values. PC-FX uses its existing core/BIOS and `heavy_cd` weight of 1; no automatic startup button input is added. Dense mode uses its configured resource limit, while normal-mode limits remain unchanged. Performance of a dense group containing PC-FX still needs checking on your hardware.

## Development and tests

```powershell
python initialize_config.py
python -m unittest discover -v
```

The repository includes Windows regression tests. Historical code used for comparison is confined to `tests_fixtures/`. Run the tests before distributing a changed build. This does not establish long-term compatibility with every system, ROM, or PC.

See [resource ownership and cleanup](docs/OWNERSHIP_NOTES.md) (Japanese) for responsibilities involving processes, cores, rendering resources, and configuration.

## Repository and personal data

Runtime configuration, favorites, ROM catalogs, logs, saves, and generated title metadata are excluded by `.gitignore`. Shareable configuration examples are provided in `config.example.json` and `systems.example/`. Environment-specific investigation records from the original distribution folder are not included.

## License

Unless otherwise stated, original RetroNativeSaver source code, tests, scripts, documentation, configuration examples, and other original project material are provided under **GNU General Public License version 3 only (SPDX: `GPL-3.0-only`)**. See [COPYRIGHT](COPYRIGHT) for the copyright notice and scope, and [LICENSE](LICENSE) for the full license text. The license text is an unmodified copy of the [official GNU text](https://www.gnu.org/licenses/gpl-3.0.txt).

This software is provided without warranty. Redistribution and modification are permitted under the terms of GPL v3.

The X1 `xmil-libretro` source and its custom modifications retain the upstream licensing scheme. Its root LICENSE is BSD 3-Clause, and some libretro headers use MIT. Copyright, permission, and disclaimer notices are preserved; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [third_party/licenses/](third_party/licenses/) document their scope and contain the original notices. External cores remain subject to their respective licenses.

The build copies the project's license documents and third-party documentation and source archive into the distribution folder. When publishing executables, also provide the corresponding project source and build instructions.
