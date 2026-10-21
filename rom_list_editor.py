"""Blacklist browser and additive whitelist editor; no emulator initialization."""
from ui_text import tr as _tr
import datetime
import json
import os
from pathlib import Path
import tempfile
import uuid


def read_state(path, kind):
    path = Path(path)
    raw = path.read_bytes() if path.exists() else None
    data = json.loads(raw.decode('utf-8-sig')) if raw is not None else {'version': 1, 'systems': {}}
    if not isinstance(data, dict) or not isinstance(data.get('systems'), dict):
        raise ValueError(_tr('{v0}: systems の形式が正しくありません。保存せず終了します。', v0=path.name))
    for name, roms in data['systems'].items():
        if not name.strip() or not isinstance(roms, list if kind == 'white' else dict):
            raise ValueError(_tr('{v0}: 機種別一覧の形式が正しくありません。', v0=path.name))
        if kind == 'white' and any(not isinstance(r, str) or not r.strip() for r in roms):
            raise ValueError(_tr('{v0}: ROM名の形式が正しくありません。', v0=path.name))
        if kind == 'black' and any(not isinstance(e, dict) for e in roms.values()):
            raise ValueError(_tr('{v0}: 障害記録の形式が正しくありません。', v0=path.name))
    return data, raw


def white_keys(data):
    return {(s.casefold(), r.casefold()) for s, roms in data['systems'].items() for r in roms}


def blacklist_rows(black, white):
    registered = white_keys(white)
    return [dict(system=s, rom=r, registered=(s.casefold(), r.casefold()) in registered,
                 blocked=bool(e.get('blacklisted', False)), failures=e.get('failure_sessions', 0),
                 reason=_tr('手動登録') if e.get('manual_blacklisted') else e.get('last_failure_kind', ''),
                 when=e.get('manual_blacklisted_utc', '') if e.get('manual_blacklisted') else e.get('last_failure_utc', ''))
            for s, roms in sorted(black['systems'].items()) for r, e in sorted(roms.items())]


def add_to_whitelist(path, selected, seed=None):
    """Reload immediately before adding; preserve unknown fields and other registrations."""
    path = Path(path)
    data, original = read_state(path, 'white')
    if original is None and seed and Path(seed).exists():
        data, _ = read_state(seed, 'white')
    keys = white_keys(data)
    added = 0
    for system, rom in selected:
        if not isinstance(system, str) or not system.strip() or not isinstance(rom, str) or not rom.strip():
            raise ValueError(_tr('機種名とROM名が必要です。'))
        key = (system.casefold(), rom.casefold())
        if key in keys:
            continue
        stored = next((s for s in data['systems'] if s.casefold() == system.casefold()), system)
        data['systems'].setdefault(stored, []).append(rom)
        keys.add(key)
        added += 1
    if not added:
        return 0, None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    backup = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as f:
            temp = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise RuntimeError(_tr('保存中に別の変更を検出しました。「再読み込み」してやり直してください。'))
        if original is not None:
            stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup = path.with_name(path.name + '.' + stamp + '.' + uuid.uuid4().hex[:8] + '.bak')
            with backup.open('xb') as f:
                f.write(original)
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
    return added, backup


def show_rom_list_editor(app_dir, config_path):
    import tkinter as tk
    from tkinter import ttk, messagebox
    from ui_text import configure_from_path
    configure_from_path(config_path)

    cfg = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    def resolve(key, default):
        path = Path(cfg.get(key) or default)
        return path if path.is_absolute() else Path(app_dir) / path
    black_path = resolve('persistent_rom_blacklist_file', 'state/persistent_rom_blacklist.json')
    white_path = resolve('persistent_rom_whitelist_file', 'state/persistent_rom_whitelist.json')
    seed_path = resolve('persistent_rom_whitelist_seed_file', 'persistent_rom_whitelist.default.json')
    root = tk.Tk()
    root.title(_tr('Retro Native Saver — ブラックリストからホワイトリストへ'))
    root.geometry('1120x620')
    root.minsize(800, 420)
    frame = ttk.Frame(root, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=_tr('再表示したいROMを選択し、ホワイトリストへ登録してください。Ctrl / Shiftで複数選択できます。')).pack(anchor='w')
    ttk.Label(frame, text=_tr('変更は次回のセーバー起動から反映します。登録後も、実行中に異常が出たROMはその回だけ除外されます。')).pack(anchor='w', pady=(4, 8))
    if not cfg.get('persistent_rom_whitelist_enabled', True):
        ttk.Label(frame, text=_tr('注意：config.jsonでホワイトリストが無効です。有効にするまで登録内容は適用されません。'), foreground='#b00020').pack(anchor='w')
    search = tk.StringVar()
    include_history = tk.BooleanVar(value=False)
    status = tk.StringVar()
    bar = ttk.Frame(frame)
    bar.pack(fill='x', pady=8)
    ttk.Label(bar, text=_tr('検索：')).pack(side='left')
    ttk.Entry(bar, textvariable=search, width=45).pack(side='left', padx=6)
    ttk.Checkbutton(bar, text=_tr('除外前の失敗記録も表示'), variable=include_history).pack(side='left')
    area = ttk.Frame(frame)
    area.pack(fill='both', expand=True)
    columns = ('system', 'rom', 'status', 'failures', 'reason', 'when')
    table = ttk.Treeview(area, columns=columns, show='headings', selectmode='extended')
    for col, title, width in zip(columns, (_tr('機種'), _tr('ROMファイル'), _tr('状態'), _tr('失敗回数'), _tr('直近の理由'), _tr('最終失敗（UTC）')), (150, 420, 130, 75, 130, 190)):
        table.heading(col, text=title)
        table.column(col, width=width, minwidth=65, stretch=col == 'rom')
    vertical = ttk.Scrollbar(area, orient='vertical', command=table.yview)
    horizontal = ttk.Scrollbar(area, orient='horizontal', command=table.xview)
    table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    table.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    area.rowconfigure(0, weight=1)
    area.columnconfigure(0, weight=1)
    rows = []
    visible = {}

    def render(*_):
        table.delete(*table.get_children())
        visible.clear()
        query = search.get().strip().casefold()
        for row in rows:
            if not row['blocked'] and not include_history.get():
                continue
            if query and query not in (row['system'] + ' ' + row['rom'] + ' ' + str(row['reason'])).casefold():
                continue
            label = _tr('登録済み（許可）') if row['registered'] else (_tr('ブラックリスト') if row['blocked'] else _tr('失敗記録のみ'))
            item = table.insert('', 'end', values=(row['system'], row['rom'], label, row['failures'], row['reason'], row['when']))
            visible[item] = row
        status.set(_tr('表示 {v0} 件 / 障害記録 {v1} 件', v0=len(visible), v1=len(rows)))
        update_button()

    def update_button(*_):
        eligible = any(i in visible and not visible[i]['registered'] for i in table.selection())
        add_button.configure(state='normal' if eligible else 'disabled')

    def reload():
        nonlocal rows
        try:
            black, _ = read_state(black_path, 'black')
            white, raw = read_state(white_path, 'white')
            if raw is None and seed_path.exists():
                white, _ = read_state(seed_path, 'white')
            rows = blacklist_rows(black, white)
            render()
        except Exception as exc:
            rows = []
            render()
            status.set(_tr('読み込みに失敗しました。ファイルを確認して再読み込みしてください。'))
            messagebox.showerror(_tr('読み込みエラー'), str(exc), parent=root)

    def register():
        selected = [(visible[i]['system'], visible[i]['rom']) for i in table.selection() if i in visible and not visible[i]['registered']]
        try:
            count, backup = add_to_whitelist(white_path, selected, seed_path)
        except Exception as exc:
            messagebox.showerror(_tr('保存できませんでした'), str(exc), parent=root)
            return
        reload()
        status.set(_tr('{v0} 件を登録しました。次回起動から反映します。', v0=count))
        messagebox.showinfo(_tr('登録完了'), _tr('{v0} 件をホワイトリストに登録しました。\nブラックリストの履歴は保持しています。', v0=count) + (_tr('\n\nバックアップ：\n{v0}', v0=backup) if backup else ''), parent=root)

    buttons = ttk.Frame(frame)
    buttons.pack(fill='x', pady=(12, 6))
    add_button = ttk.Button(buttons, text=_tr('選択したROMをホワイトリストへ登録'), command=register)
    add_button.pack(side='left')
    ttk.Button(buttons, text=_tr('再読み込み'), command=reload).pack(side='left', padx=8)
    ttk.Button(buttons, text=_tr('閉じる'), command=root.destroy).pack(side='right')
    ttk.Label(frame, textvariable=status).pack(anchor='w')
    ttk.Label(frame, text=_tr('保存先：{v0}', v0=white_path), wraplength=1050).pack(anchor='w', pady=(4, 0))
    search.trace_add('write', render)
    include_history.trace_add('write', render)
    table.bind('<<TreeviewSelect>>', update_button)
    reload()
    root.mainloop()
