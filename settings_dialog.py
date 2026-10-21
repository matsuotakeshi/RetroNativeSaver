"""Screensaver configuration UI; existing runtime JSON remains the source of truth."""
from ui_text import tr as _tr
import os
from pathlib import Path
import subprocess
import sys

from settings_store import (SettingsDocument, GENERAL, TITLE, GROUP, WEIGHTS, DISABLED,
                            display_values, group_options, group_rows)

SYSTEM_NAMES = {
    'megadrive': 'Mega Drive', 'megacd': 'Mega-CD', 'pcengine': 'PC Engine',
    'pcenginecd': 'CD-ROM²', 'cdrom2': 'CD-ROM²', 'pcfx': 'PC-FX',
    'gb': 'GB', 'gbc': 'GBC', 'gba': 'GBA', 'fds': 'FDS', 'nes': 'NES',
    'snes': 'SNES', 'fbneo': 'FinalBurn Neo', 'msx': 'MSX', 'x1': 'X1',
    'x68000': 'X68000', 'pc88': 'PC-8801', 'pc98': 'PC-9801', 'neocd': 'Neo Geo CD',
}


def parse_config_args(argv, app_dir):
    """Read /c ownership separately to retain the legacy saver/preview parser."""
    from log_output import config_path
    owner = None
    for index, arg in enumerate(argv):
        low = arg.lower()
        if low in ('/c', '-c') or low.startswith(('/c:', '-c:')):
            raw = arg.split(':', 1)[1] if ':' in arg else (argv[index + 1] if index + 1 < len(argv) else '')
            try:
                owner = int(raw, 0) if str(raw).lower().startswith('0x') else int(raw, 10)
                if not 0 < owner < 2 ** 64:
                    owner = None
            except ValueError:
                owner = None
    return config_path(argv, app_dir).resolve(), owner


def attach_owner(root, owner):
    """Set an owner (not a child parent); stale Windows/RandomSaver handles are harmless."""
    if os.name != 'nt' or not owner:
        return
    import ctypes as C
    from ctypes import wintypes as W
    user = C.WinDLL('user32', use_last_error=True)
    user.IsWindow.argtypes, user.IsWindow.restype = [W.HWND], W.BOOL
    user.GetAncestor.argtypes, user.GetAncestor.restype = [W.HWND, W.UINT], W.HWND
    setter = user.SetWindowLongPtrW if C.sizeof(C.c_void_p) == 8 else user.SetWindowLongW
    setter.argtypes, setter.restype = [W.HWND, C.c_int, C.c_ssize_t], C.c_ssize_t
    root.update_idletasks()
    if user.IsWindow(owner):
        hwnd = user.GetAncestor(root.winfo_id(), 2)
        C.set_last_error(0)
        previous = setter(hwnd, -8, owner)  # GWLP_HWNDPARENT for a top-level window.
        if not previous and C.get_last_error():
            raise C.WinError(C.get_last_error())


def management_command(app_dir, config_path, action):
    flag = {'favorites': '--favorites', 'rom_lists': '--rom-lists', 'catalog': '--update-rom-catalog'}[action]
    command = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(app_dir) / 'native_saver.py')]
    return command + [flag, '--config', str(config_path)]


class SettingsDialog:
    def __init__(self, root, app_dir, document):
        import tkinter as tk
        from tkinter import ttk
        from app_version import APP_VERSION
        from ui_text import configure, LANGUAGE_LABELS, language_label
        configure(document.data)
        self.root, self.app_dir, self.document = root, Path(app_dir), document
        self.variables, self.initial, self.controls = {}, {}, {}
        self.member_variables = []
        self.processes = {}
        self.catalog_needs_update = False
        root.title(_tr('RetroNativeSaver {v0} — 設定', v0=APP_VERSION))
        root.geometry('880x760')
        root.minsize(800, 620)
        root.protocol('WM_DELETE_WINDOW', self.cancel)
        style = ttk.Style(root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        outer = ttk.Frame(root, padding=14)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text=_tr('設定は次回のスクリーンセーバー起動から反映されます。')).pack(anchor='w')
        ttk.Label(outer, text=str(document.path), wraplength=760, foreground='#555555').pack(anchor='w', pady=(3, 10))
        notebook = ttk.Notebook(outer)
        notebook.pack(fill='both', expand=True)
        self.notebook = notebook
        values = display_values(document.data)
        for label, fields, note in (
            (_tr('全般'), GENERAL, _tr('表示時間は機種別設定が優先されます。ランダム幅・上限 FPS は非同期表示に適用されます。\nRetroArchのEXEはEnterでゲームを開くときに使用します。空欄では従来どおり自動検出します。\nログは初期状態でオフです。オンにすると通常の監視・エラーログを保存します。')),
            (_tr('タイトル表示'), TITLE, _tr('1行スクロール時は機種名とタイトルを同じ文字サイズで表示します。色は #RRGGBB で指定します。')),
            (_tr('グループ表示'), GROUP, _tr('非同期表示を有効にした全画面起動で抽選します。割合は 50:50 や 15:85 のように指定できます。\n上限 FPS は全般の上限との小さい方です。枠数・負荷上限・グループ構成は既存設定を維持します。')),
        ):
            page = self.scroll_page(notebook, label)
            ttk.Label(page, text=note, wraplength=700, foreground='#555555').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))
            for row, field in enumerate(fields, 1):
                raw = values[field.path]
                if field.kind == 'bool':
                    # Non-boolean legacy values remain untouched unless explicitly edited.
                    strict = field.path in (('log_output_enabled',), ('single_system_mode', 'enabled'))
                    var = tk.BooleanVar(root, value=(raw is True) if strict else bool(raw))
                    control = ttk.Checkbutton(page, text=_tr(field.label), variable=var)
                    control.grid(row=row, column=0, columnspan=2, sticky='w', pady=6)
                else:
                    text = ('' if field.kind == 'path' and raw is None else
                            format(raw, '.15g') if isinstance(raw, (int, float)) and not isinstance(raw, bool) else str(raw))
                    var = tk.StringVar(root, value=language_label(raw) if field.kind == 'language' else text)
                    ttk.Label(page, text=_tr(field.label)).grid(row=row, column=0, sticky='w', pady=5, padx=(0, 20))
                    if field.kind == 'language':
                        control = ttk.Combobox(page, textvariable=var, values=LANGUAGE_LABELS, state='readonly', width=30)
                        control.grid(row=row, column=1, sticky='ew', pady=5)
                    elif field.kind == 'path':
                        from system_settings_editor import browse_path
                        holder = ttk.Frame(page)
                        holder.grid(row=row, column=1, sticky='ew', pady=5)
                        control = ttk.Entry(holder, textvariable=var, width=38)
                        control.pack(side='left', fill='x', expand=True)
                        ttk.Button(holder, text=_tr('参照…'), width=7,
                                   command=lambda v=var: browse_path(root, v, 'exe', self.app_dir)).pack(side='left', padx=(6, 0))
                    else:
                        control = ttk.Entry(page, textvariable=var, width=20)
                        control.grid(row=row, column=1, sticky='w', pady=5)
                self.variables[field.path], self.controls[field.path] = var, control
                self.initial[field.path] = var.get()
            if fields is GROUP:
                box = ttk.LabelFrame(page, text=_tr('グループ内で抽選する機種（通常表示には影響しません）'), padding=10)
                box.grid(row=len(fields) + 1, column=0, columnspan=2, sticky='ew', pady=(16, 6))
                disabled = group_options(document.data).get('disabled_systems', [])
                disabled_canonical = {self.canonical(sid) for sid in disabled}
                member_vars = {}
                for row, members in enumerate(group_rows(document.data)):
                    ttk.Label(box, text=f'{row + 1}').grid(row=row, column=0, sticky='w', padx=(0, 10), pady=4)
                    group = ttk.Frame(box)
                    group.grid(row=row, column=1, sticky='w')
                    for col, sid in enumerate(members):
                        canonical = self.canonical(sid)
                        if canonical not in member_vars:
                            member_vars[canonical] = tk.BooleanVar(root, value=canonical not in disabled_canonical)
                        var = member_vars[canonical]
                        ttk.Checkbutton(group, text=SYSTEM_NAMES.get(sid, sid), variable=var).grid(row=col // 4, column=col % 4, sticky='w', padx=(0, 10), pady=3)
                        self.member_variables.append((sid, var, var.get()))
        from system_settings_editor import SystemSettingsEditor
        self.system_editor = SystemSettingsEditor(notebook, self.app_dir, document.data, self.scroll_page)
        ttk.Label(outer, text=_tr('言語の変更は「適用／OK」で保存後、画面を開き直すと反映されます。'), wraplength=820).pack(anchor='w', pady=(6, 0))
        management = ttk.LabelFrame(outer, text=_tr('管理画面・一覧更新'), padding=10)
        management.pack(fill='x', pady=(12, 8))
        self.management_buttons = {}
        for action, label in (('favorites', _tr('お気に入り・キー入力…')), ('rom_lists', _tr('ブラック／ホワイトリスト…')), ('catalog', _tr('ROM一覧を更新'))):
            button = ttk.Button(management, text=label, command=lambda a=action: self.launch_management(a))
            button.pack(side='left', padx=(0, 8))
            self.management_buttons[action] = button
        ttk.Label(outer, text=_tr('管理画面は保存済みの設定を使います。管理画面側で保存した変更はキャンセルでは戻りません。'), wraplength=760).pack(anchor='w')
        self.status = tk.StringVar(root, value=_tr('変更した項目だけ保存します。保存時には元のJSONをバックアップします。'))
        ttk.Label(outer, textvariable=self.status, wraplength=760, foreground='#555555').pack(anchor='w', pady=8)
        buttons = ttk.Frame(outer)
        buttons.pack(fill='x')
        for text, command in ((_tr('適用'), self.apply), (_tr('キャンセル'), self.cancel), ('OK', self.ok)):
            ttk.Button(buttons, text=text, command=command).pack(side='right', padx=(8, 0))
        root.bind('<Escape>', lambda event: self.cancel())

    @staticmethod
    def canonical(sid):
        return 'pcenginecd' if sid == 'cdrom2' else sid

    @staticmethod
    def scroll_page(notebook, label):
        import tkinter as tk
        from tkinter import ttk
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=label)
        canvas = tk.Canvas(frame, highlightthickness=0)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        page = ttk.Frame(canvas, padding=14)
        item = canvas.create_window((0, 0), window=page, anchor='nw')
        page.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        def wheel(event):
            if str(event.widget).startswith(str(frame)) and event.delta:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
                return 'break'
        notebook.winfo_toplevel().bind('<MouseWheel>', wheel, add='+')
        return page

    def changes(self):
        changes = {path: var.get() for path, var in self.variables.items() if var.get() != self.initial[path]}
        if ('ui_language',) in changes:
            from ui_text import language_value
            changes[('ui_language',)] = language_value(changes[('ui_language',)])
        if any(path in changes for path in WEIGHTS):
            changes.update({path: self.variables[path].get() for path in WEIGHTS})
        disabled = list(group_options(self.document.data).get('disabled_systems', []))
        edited = False
        for sid, var, initial in self.member_variables:
            if var.get() == initial:
                continue
            edited = True
            disabled = [s for s in disabled if self.canonical(s) != self.canonical(sid)]
            if not var.get():
                disabled.append(sid)
        if edited:
            changes[DISABLED] = disabled
        return changes

    def apply(self):
        from tkinter import messagebox
        if 'catalog' in self.processes:
            messagebox.showinfo(_tr('ROM一覧を更新中'), _tr('一覧更新の完了後に設定を保存してください。'), parent=self.root)
            return False
        saved = []
        try:
            changes = self.changes()
            plans = self.system_editor.plans()
            documents = [(self.document, changes)] + [(draft.document, edits) for draft, edits in plans]
            # Validate every edit and detect external changes before writing any file.
            for document, edits in documents:
                try:
                    document.check_changes(edits)
                except Exception as exc:
                    raise ValueError(f'{document.path.name}\n{exc}') from exc
            backup = self.document.save(changes)
            if backup:
                saved.append(str(self.document.path))
            self.initial = {path: var.get() for path, var in self.variables.items()}
            self.member_variables = [(sid, var, var.get()) for sid, var, _ in self.member_variables]
            from fixed_rom_catalog import SCAN_KEYS
            for draft, edits in plans:
                backup = draft.document.save(edits)
                draft.accept_saved()
                if backup:
                    saved.append(str(draft.document.path))
                    if any(path[0] in (*SCAN_KEYS, 'enabled') for path in edits):
                        self.catalog_needs_update = True
            self.system_editor.refresh_labels()
            self.system_editor.refresh_inherited(self.document.data)
            text = _tr('{v0}ファイルを保存しました。次回起動から反映します。', v0=len(saved)) if saved else _tr('変更はありません。')
            if self.catalog_needs_update:
                text += _tr(' ROM検索条件を変更したため「ROM一覧を更新」を実行してください。')
            self.status.set(text)
            return True
        except Exception as exc:
            self.system_editor.refresh_labels()
            text = str(exc)
            if saved:
                text += _tr('\n\n保存済み（バックアップ作成済み）：\n') + '\n'.join(saved)
                text += _tr('\n\n残りの変更は未保存です。原因を解消して再度「適用」してください。')
            self.status.set(_tr('保存できなかった変更が残っています。'))
            messagebox.showerror(_tr('設定を保存できません'), text, parent=self.root)
            return False

    def ok(self):
        if self.apply():
            self.cancel()

    def cancel(self):
        from tkinter import messagebox
        process = self.processes.get('catalog')
        if process is not None and process.poll() is None:
            messagebox.showinfo(_tr('ROM一覧を更新中'), _tr('一覧更新の完了後に閉じてください。'), parent=self.root)
            return
        self.root.destroy()

    def launch_management(self, action):
        from tkinter import messagebox
        if self.changes() or self.system_editor.plans():
            choice = messagebox.askyesnocancel(_tr('設定を保存しますか'), _tr('管理画面を開く前に変更を保存しますか？\n「いいえ」は保存済みの設定で開きます。'), parent=self.root)
            if choice is None or (choice and not self.apply()):
                return
        try:
            environment = {key: value for key, value in os.environ.items() if not key.startswith('RNS_')}
            process = subprocess.Popen(management_command(self.app_dir, self.document.path, action),
                cwd=self.app_dir, env=environment, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes[action] = process
            self.management_buttons[action].state(['disabled'])
            if action == 'catalog':
                self.status.set(_tr('ROM一覧を更新しています…'))
            self.root.after(300, lambda: self.poll_management(action, process))
        except Exception as exc:
            messagebox.showerror(_tr('管理画面を開けません'), str(exc), parent=self.root)

    def poll_management(self, action, process):
        from tkinter import messagebox
        code = process.poll()
        if code is None:
            self.root.after(300, lambda: self.poll_management(action, process))
            return
        self.processes.pop(action, None)
        self.management_buttons[action].state(['!disabled'])
        if code:
            self.status.set(_tr('処理に失敗しました。設定・フォルダーの指定と書き込み権限を確認してください。'))
            messagebox.showerror(_tr('処理に失敗しました'), _tr('終了コード: {v0}\n設定・フォルダーの指定と書き込み権限を確認してください。', v0=code), parent=self.root)
        elif action == 'catalog':
            self.catalog_needs_update = False
            self.status.set(_tr('ROM一覧を更新しました。'))


def show_settings_dialog(app_dir, config_path, owner=None):
    import tkinter as tk
    from ui_text import configure_from_path
    configure_from_path(config_path)
    document = SettingsDocument(config_path)
    root = tk.Tk()
    root.withdraw()
    try:
        SettingsDialog(root, app_dir, document)
        root.deiconify()
        # Tk replaces/reconfigures its native wrapper when it is first mapped.
        # Assign the external owner only after that transition has completed.
        root.update_idletasks()
        attach_owner(root, owner)
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
