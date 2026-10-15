"""Favorite configuration and catalog matching; no emulator or Win32 imports."""
import json
import os
from pathlib import Path
import tempfile
from copy import deepcopy
from favorite_titles import load_titles, display_title, title_database, choose_roms


def validate_favorites(data):
    if not isinstance(data, dict) or not isinstance(data.get('enabled', True), bool):
        raise ValueError('お気に入り設定の形式が正しくありません。')
    items = data.get('items', [])
    if not isinstance(items, list):
        raise ValueError('items は一覧で指定してください。')
    clean = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) and item[k].strip() for k in ('system', 'rom')
        ):
            raise ValueError('各項目には機種IDとROMファイルが必要です。')
        entry = {k: item[k].strip() for k in ('system', 'rom')}
        if 'startup_input' in item:
            from favorite_input import validate_input
            entry['startup_input'] = validate_input(item['startup_input'])
        key = (entry['system'].casefold(), entry['rom'].replace('\\', '/').casefold())
        if key not in seen:
            seen.add(key)
            clean.append(entry)
    return {'enabled': data.get('enabled', True), 'items': clean}


def load_favorites(path):
    path = Path(path)
    if not path.exists():
        return {'enabled': True, 'items': []}
    return validate_favorites(json.loads(path.read_text(encoding='utf-8-sig')))


def save_favorites(path, data):
    path = Path(path)
    data = validate_favorites(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace only after a complete write; leave the existing file on failure.
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as f:
            temp_name = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(temp_name, path)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()


def favorite_candidates(systems, catalogs, data, log=print):
    """Match only the supplied catalog, including its session/content safety filters."""
    if not data.get('enabled', True):
        return []
    by_id = {str(s['id']).casefold(): s for s in systems}
    result, seen = [], set()
    canonical_catalogs = {}
    lexical_catalogs = {}
    from catalog_paths import CatalogPaths
    canonical = CatalogPaths().canonical

    for item in data.get('items', []):
        system = by_id.get(item['system'].casefold())
        if system is None:
            log(f"[favorites] unavailable system: {item['system']}")
            continue
        wanted = item['rom'].replace('\\', '/').casefold()
        # A bare basename must identify exactly one ROM in this system.
        sid = system['id']
        if sid not in lexical_catalogs:
            names, paths = {}, {}
            for p in catalogs.get(sid, []):
                names.setdefault(p.name.casefold(), []).append(p)
                paths.setdefault(str(p).replace('\\', '/').casefold(), []).append(p)
            lexical_catalogs[sid] = names, paths
        names, paths = lexical_catalogs[sid]
        matches = (names if '/' not in wanted else paths).get(wanted, [])
        if not matches and '/' in wanted:
            sid = system['id']
            if sid not in canonical_catalogs:
                index = {}
                saved_paths = getattr(catalogs, 'canonical_paths', {})
                for rom in catalogs.get(sid, []):
                    key = saved_paths.get(str(rom))
                    if key is None:
                        key = canonical(rom)
                    index.setdefault(key, []).append(rom)
                canonical_catalogs[sid] = index
            matches = canonical_catalogs[sid].get(canonical(item['rom']), [])
        if len(matches) != 1:
            log(f"[favorites] unavailable or ambiguous (missing/filtered): [{system['id']}] {item['rom']}")
            continue
        rom = matches[0]
        key = (system['id'], str(rom).casefold())
        if key not in seen:
            seen.add(key)
            if 'startup_input' in item:
                from favorite_input import validate_input
                system = dict(system, _favorite_startup_input=validate_input(item['startup_input']))
            result.append((system, rom))
    return result


def show_favorites_editor(app_dir, systems_dir, favorites_path):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title('Retro Native Saver — お気に入り設定')
    root.geometry('1160x670')
    root.minsize(950, 540)
    try:
        data = load_favorites(favorites_path)
        systems = []
        for path in sorted(Path(systems_dir).glob('*.json')):
            system = json.loads(path.read_text(encoding='utf-8-sig'))
            if system.get('enabled', True):
                systems.append(system)
    except Exception as exc:
        messagebox.showerror('設定を読み込めません', str(exc), parent=root)
        root.destroy()
        return
    title_maps = {str(s['id']).casefold(): load_titles(app_dir, s) for s in systems}
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill='both', expand=True)
    enabled = tk.BooleanVar(value=data['enabled'])
    ttk.Checkbutton(frame, text='毎サイクル、お気に入りからランダムに1本を必ず選ぶ', variable=enabled).pack(anchor='w')
    ttk.Label(frame, text='先頭の1枠に表示します。残りの枠は通常のランダム表示です。').pack(anchor='w', pady=(4, 12))
    row = ttk.Frame(frame)
    row.pack(fill='x')
    ttk.Label(row, text='機種：').pack(side='left')
    names = [f"{s.get('name', s['id'])}  ({s['id']})" for s in systems]
    choice = ttk.Combobox(row, values=names, state='readonly', width=40)
    choice.pack(side='left', padx=6)
    if names:
        choice.current(0)
    from favorite_input_editor import InputEditor
    from favorite_input import input_summary
    input_editor = InputEditor(frame)
    input_editor.pack(fill='x', pady=(12, 0))
    items = list(data['items'])
    area = ttk.Frame(frame)
    area.pack(fill='both', expand=True, pady=12)
    table = ttk.Treeview(area, columns=('system', 'title', 'input', 'rom'), show='headings', selectmode='extended')
    table.heading('system', text='機種')
    table.heading('title', text='タイトル')
    table.heading('input', text='自動入力')
    table.heading('rom', text='ROMファイル')
    table.column('input', width=210, stretch=False)
    table.column('system', width=130, stretch=False)
    table.column('title', width=310)
    table.column('rom', width=380)
    scroll = ttk.Scrollbar(area, orient='vertical', command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    table.pack(side='left', fill='both', expand=True)
    scroll.pack(side='right', fill='y')
    dirty = False

    def refresh():
        table.delete(*table.get_children())
        for i, entry in enumerate(items):
            title = display_title(entry['rom'], title_maps.get(entry['system'].casefold(), {}))
            table.insert('', 'end', iid=str(i), values=(entry['system'], title, input_summary(entry.get('startup_input')), entry['rom']))

    def add():
        nonlocal dirty
        if choice.current() < 0:
            return
        try:
            auto_input = input_editor.value()
        except ValueError as exc:
            messagebox.showerror('自動入力の設定を確認してください', str(exc), parent=root)
            return
        system = systems[choice.current()]
        folder = Path(system.get('rom_dir', app_dir))
        if title_database(system):
            paths = choose_roms(root, app_dir, system, title_maps.get(str(system['id']).casefold(), {}))
        else:
            paths = filedialog.askopenfilenames(parent=root, title='お気に入りにするROMを選択（複数選択可）',
                                                initialdir=str(folder if folder.exists() else app_dir))
        if paths:
            items.extend(dict(system=system['id'], rom=str(Path(p)),
                              **({'startup_input': deepcopy(auto_input)} if auto_input else {})) for p in paths)
            items[:] = validate_favorites({'items': items})['items']
            dirty = True
            refresh()

    def load_selected(event=None):
        selection = table.selection()
        if selection:
            input_editor.load(items[int(selection[0])].get('startup_input'))

    def apply_input():
        nonlocal dirty
        selection = table.selection()
        if not selection:
            messagebox.showinfo('項目を選択してください', '自動入力を変更するお気に入りを選択してください。', parent=root)
            return
        try:
            value = input_editor.value()
        except ValueError as exc:
            messagebox.showerror('自動入力の設定を確認してください', str(exc), parent=root)
            return
        for selected in selection:
            entry = items[int(selected)]
            if value is None:
                entry.pop('startup_input', None)
            else:
                entry['startup_input'] = deepcopy(value)
        dirty = True
        refresh()

    table.bind('<<TreeviewSelect>>', load_selected)

    def remove():
        nonlocal dirty
        selected = sorted((int(i) for i in table.selection()), reverse=True)
        for i in selected:
            del items[i]
        dirty = dirty or bool(selected)
        refresh()

    def save():
        nonlocal dirty
        try:
            save_favorites(favorites_path, {'enabled': enabled.get(), 'items': items})
        except Exception as exc:
            messagebox.showerror('保存できません', str(exc), parent=root)
            return False
        dirty = False
        data['enabled'] = enabled.get()
        messagebox.showinfo('保存しました', '次の表示サイクルから反映されます。', parent=root)
        return True

    def close():
        if dirty or enabled.get() != data['enabled']:
            answer = messagebox.askyesnocancel('変更の保存', '変更を保存して閉じますか？', parent=root)
            if answer is None or (answer and not save()):
                return
        root.destroy()

    ttk.Button(row, text='ROMを追加…', command=add).pack(side='left')
    buttons = ttk.Frame(frame)
    buttons.pack(side='bottom', fill='x', before=area)
    ttk.Button(buttons, text='自動入力を適用', command=apply_input).pack(side='left', padx=(0,8))
    ttk.Button(buttons, text='選択した項目を削除', command=remove).pack(side='left')
    ttk.Button(buttons, text='閉じる', command=close).pack(side='right')
    ttk.Button(buttons, text='保存', command=save).pack(side='right', padx=8)
    ttk.Label(frame, text='お気に入り枠ではブラックリストを無視します。負荷上限・起動条件・実行中の障害隔離は維持します。\n全件利用できない場合は通常表示を続け、理由をログに記録します。').pack(anchor='w', pady=(12, 0))
    refresh()
    root.protocol('WM_DELETE_WINDOW', close)
    root.mainloop()


from resource_policy import _resource_group_usage_from_picks, _resource_group_can_add


def load_cycle_favorites(favorites_path, systems, catalogs, failed_roms):
    try:
        favorite_settings = load_favorites(favorites_path)
        eligible_systems = [x for x in systems if x.get('enabled', True)
                            and str(x.get('render_backend', 'software')).lower()
                            in ('software', 'opengl', 'glcore')]
        favorites = [pair for pair in favorite_candidates(eligible_systems, catalogs, favorite_settings)
                     if str(pair[1]) not in failed_roms]
        if favorite_settings.get('enabled', True) and favorite_settings['items'] and not favorites:
            print("[favorites] no available favorites; using normal selection", flush=True)
    except (OSError, ValueError) as exc:
        favorites = []
        print(f"[favorites] configuration error; using normal selection: {exc}", flush=True)
    return favorites


def cycle_favorite_retries(i, system, rom, favorites, picks, slot_count, cfg):
    favorite_retries = None
    if i == 0 and any(x['id'] == system['id'] and r == rom for x, r in favorites):
        other_picks = picks[1:]
        other_usage = _resource_group_usage_from_picks(other_picks)
        favorite_retries = [
            (x, r) for x, r in favorites
            if sum(1 for other, _ in other_picks if other['id'] == x['id'])
               < int(x.get('max_concurrent', slot_count))
            and _resource_group_can_add(x, other_usage, cfg)
            and ((x['id'] == system['id'] and r == rom)
                 or not any(other['id'] == x['id'] and other_rom == r
                            for other, other_rom in other_picks))
        ]
    return favorite_retries


def record_favorite_startup(initial_system, system, rom, favorite_retries, cycle_group_usage):
    from resource_policy import replace_cycle_usage
    replace_cycle_usage(initial_system, system, cycle_group_usage)
    favorite_keys = {(x['id'], str(r)) for x, r in favorite_retries}
    status = 'READY' if (system['id'], str(rom)) in favorite_keys else 'normal fallback'
    print(f"[favorites] {status}: [{system['id']}] {rom.name}", flush=True)
