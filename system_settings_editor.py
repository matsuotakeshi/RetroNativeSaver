"""Machine selector and typed settings form; all edits stay in drafts until Apply."""
from ui_text import tr as _tr
from pathlib import Path

from system_settings import load_drafts, default_value, display_value


def browse_path(parent, variable, kind, app_dir):
    from tkinter import filedialog
    current = Path(variable.get()) if variable.get().strip() else Path(app_dir)
    if not current.is_absolute():
        current = Path(app_dir) / current
    initial = current if current.is_dir() else current.parent
    if not initial.is_dir():
        initial = Path(app_dir)
    if kind == 'directory':
        value = filedialog.askdirectory(parent=parent, initialdir=str(initial))
    else:
        filters = {'exe': [(_tr('実行ファイル'), '*.exe')], 'core': [(_tr('libretroコア'), '*.dll')], 'json': [('JSON', '*.json')]}
        value = filedialog.askopenfilename(parent=parent, initialdir=str(initial),
                    filetypes=filters.get(kind, []) + [(_tr('すべてのファイル'), '*.*')])
    if value:
        variable.set(value)


class SystemSettingsEditor:
    def __init__(self, notebook, app_dir, common, scroll_page):
        import tkinter as tk
        from tkinter import ttk
        self.app_dir = Path(app_dir)
        self.directory, self.entries = load_drafts(app_dir, common)
        self.current = None
        self.variables, self.inherited, self.texts = {}, {}, {}
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text=_tr('機種別'))
        self.frame = frame
        selection = ttk.Frame(frame)
        selection.pack(fill='x')
        ttk.Label(selection, text=_tr('機種：')).pack(side='left')
        self.choice = ttk.Combobox(selection, values=[item[0] for item in self.entries], state='readonly')
        self.choice.pack(side='left', fill='x', expand=True)
        self.choice.bind('<<ComboboxSelected>>', self.select)
        self.description = tk.StringVar(frame, value=_tr('機種別設定がありません：{v0}', v0=self.directory))
        ttk.Label(frame, textvariable=self.description, wraplength=720, foreground='#555555').pack(anchor='w', pady=6)
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill='both', expand=True)
        self.pages = {name: scroll_page(self.tabs, _tr(name)) for name in ('基本', '表示・負荷', 'ROM・起動', '詳細')}
        option_page = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(option_page, text=_tr('コアオプション'))
        self.option_note = ttk.Label(option_page, wraplength=690)
        self.option_note.pack(anchor='w', pady=(0, 8))
        table_area = ttk.Frame(option_page)
        table_area.pack(fill='both', expand=True)
        self.options = ttk.Treeview(table_area, columns=('name', 'value'), show='headings', selectmode='browse')
        self.options.heading('name', text=_tr('設定名'))
        self.options.heading('value', text=_tr('値'))
        self.options.column('name', width=300)
        self.options.column('value', width=280)
        scrollbar = ttk.Scrollbar(table_area, orient='vertical', command=self.options.yview)
        self.options.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.options.pack(fill='both', expand=True)
        self.options.bind('<Double-1>', lambda event: self.edit_option())
        buttons = ttk.Frame(option_page)
        buttons.pack(fill='x', pady=(8, 0))
        self.option_buttons = []
        for name, command in ((_tr('追加…'), self.add_option), (_tr('値を変更…'), self.edit_option), (_tr('削除'), self.delete_option)):
            button = ttk.Button(buttons, text=name, command=command)
            button.pack(side='left', padx=(0, 8))
            self.option_buttons.append(button)
        if self.entries:
            self.choice.current(0)
            self.select()
        else:
            self.render_options()

    def capture(self):
        if self.current is not None:
            self.current.values.update({key: var.get() for key, var in self.variables.items()})
            self.current.values.update({key: text.get('1.0', 'end-1c') for key, text in self.texts.items()})
            self.current.inherited.update({key: var.get() for key, var in self.inherited.items()})

    def select(self, event=None):
        import tkinter as tk
        from tkinter import ttk
        self.capture()
        self.variables, self.inherited, self.texts = {}, {}, {}
        for page in self.pages.values():
            for child in page.winfo_children():
                child.destroy()
        _, self.current, error = self.entries[self.choice.current()]
        if self.current is None:
            self.description.set(_tr('このファイルは編集できません。元のJSONは変更しません。\n') + error)
            self.render_options()
            return
        draft = self.current
        self.description.set(_tr('{v0}\n機種の切り替えでは保存しません。「適用／OK」で編集中の全機種を保存します。', v0=draft.document.path))
        notes = {
            '基本': _tr('機種IDは維持します。共通／既定を選ぶと機種別の指定を外します。セーブ先は一時セーブ領域の設定が優先されます。'),
            '表示・負荷': _tr('表示時間は非同期表示で使用します。グループ表示では機種別の同時起動数より既存のグループ用上限が優先されます。'),
            'ROM・起動': _tr('ROM検索条件を変更した後は、保存してから「ROM一覧を更新」を実行してください。拡張子が空の場合は全拡張子が対象です。'),
            '詳細': _tr('コア固有の互換性設定です。必要な項目だけ変更してください。ログ用インターフェースとログの保存設定は別の項目です。'),
        }
        rows = {}
        for section, page in self.pages.items():
            page.columnconfigure(1, weight=1)
            ttk.Label(page, text=notes[section], wraplength=660, foreground='#555555').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))
            rows[section] = 1
        for field in draft.fields:
            page, row = self.pages[field.section], rows[field.section]
            rows[field.section] += 1
            raw = draft.values[field.path]
            if field.kind == 'bool':
                var = tk.BooleanVar(page, value=raw)
                ttk.Checkbutton(page, text=_tr(field.label), variable=var).grid(row=row, column=0, columnspan=2, sticky='w', pady=5)
                self.variables[field.path] = var
                continue
            ttk.Label(page, text=_tr(field.label)).grid(row=row, column=0, sticky='nw', padx=(0, 10), pady=5)
            holder = ttk.Frame(page)
            holder.grid(row=row, column=1, sticky='ew', pady=4)
            holder.columnconfigure(0, weight=1)
            if field.kind == 'lines':
                control = tk.Text(holder, height=3, width=28, wrap='none', undo=True)
                control.insert('1.0', raw)
                self.texts[field.path] = control
                control.grid(row=0, column=0, sticky='ew')
                scroll = ttk.Scrollbar(holder, orient='vertical', command=control.yview)
                scroll.grid(row=0, column=1, sticky='ns')
                control.configure(yscrollcommand=scroll.set)
                continue
            var = tk.StringVar(page, value=raw)
            self.variables[field.path] = var
            if field.choices:
                control = ttk.Combobox(holder, textvariable=var, values=field.choices, state='readonly', width=27)
            else:
                control = ttk.Entry(holder, textvariable=var, width=28)
            control.grid(row=0, column=0, sticky='ew')
            browse = None
            if field.browse:
                browse = ttk.Button(holder, text=_tr('参照…'), width=7, command=lambda v=var, k=field.browse: browse_path(self.frame, v, k, self.app_dir))
                browse.grid(row=0, column=1, padx=(6, 0))
            if field.inherit:
                inherit = tk.BooleanVar(page, value=draft.inherited[field.path])
                self.inherited[field.path] = inherit
                def state(v=inherit, c=control, b=browse):
                    c.state(['disabled'] if v.get() else ['!disabled'])
                    if b is not None:
                        b.state(['disabled'] if v.get() else ['!disabled'])
                ttk.Checkbutton(holder, text=_tr('共通／既定を使用'), variable=inherit, command=state).grid(row=1, column=0, columnspan=2, sticky='w', pady=(3, 0))
                state()
        self.render_options()

    def render_options(self):
        self.options.delete(*self.options.get_children())
        valid = self.current is not None and isinstance(self.current.options, dict)
        for button in self.option_buttons:
            button.state(['!disabled'] if valid else ['disabled'])
        self.option_names = []
        if valid:
            self.option_note.configure(text=_tr('ダブルクリックで値を変更できます。コアが受け付ける設定名・値を指定してください。変更は「適用／OK」で保存します。'))
            for index, (key, value) in enumerate(self.current.options.items()):
                self.option_names.append(key)
                self.options.insert('', 'end', iid=str(index), values=(key, str(value)))
        else:
            self.option_note.configure(text=_tr('コアオプションを編集できません。未設定の機種を選ぶか、core_options のJSON形式を確認してください。'))

    def add_option(self):
        from tkinter import simpledialog, messagebox
        if self.current is None or not isinstance(self.current.options, dict):
            return
        key = simpledialog.askstring(_tr('コアオプションの追加'), _tr('設定名'), parent=self.frame)
        if key is None:
            return
        key = key.strip()
        if not key or any(c in key for c in ('\0', '\r', '\n')):
            messagebox.showerror(_tr('設定名を確認してください'), _tr('空欄・改行は使用できません。'), parent=self.frame)
            return
        if key in self.current.options:
            messagebox.showinfo(_tr('登録済みです'), _tr('一覧から選択して「値を変更」を使ってください。'), parent=self.frame)
            return
        value = simpledialog.askstring(_tr('コアオプションの追加'), _tr('{v0} の値', v0=key), parent=self.frame)
        if value is not None:
            self.current.options[key] = value
            self.render_options()

    def edit_option(self):
        from tkinter import simpledialog
        selected = self.options.selection()
        if self.current is None or not selected:
            return
        key = self.option_names[int(selected[0])]
        value = simpledialog.askstring(_tr('コアオプションの変更'), _tr('{v0} の値', v0=key), initialvalue=str(self.current.options[key]), parent=self.frame)
        if value is not None:
            self.current.options[key] = value
            self.render_options()

    def delete_option(self):
        selected = self.options.selection()
        if self.current is not None and selected:
            del self.current.options[self.option_names[int(selected[0])]]
            self.render_options()

    def plans(self):
        self.capture()
        return [(draft, draft.changes()) for _, draft, _ in self.entries if draft is not None and draft.changes()]

    def refresh_labels(self):
        self.entries = [(f"{draft.document.data.get('name', draft.document.data['id'])} ({draft.document.data['id']}) — {draft.document.path.name}", draft, error)
                        if draft is not None else (label, draft, error) for label, draft, error in self.entries]
        selected = self.choice.current()
        self.choice.configure(values=[item[0] for item in self.entries])
        if selected >= 0:
            self.choice.current(selected)

    def refresh_inherited(self, common):
        """Refresh only committed inheritance; do not discard an unsaved override."""
        for _, draft, _ in self.entries:
            if draft is None:
                continue
            for field in draft.fields:
                path = field.path
                if field.inherit and draft.inherited[path] and draft.initial_inherited[path]:
                    value = display_value(field, default_value(field, draft.document.data, common))
                    draft.values[path] = draft.initial[path] = value
                    if draft is self.current and path in self.variables:
                        self.variables[path].set(value)
