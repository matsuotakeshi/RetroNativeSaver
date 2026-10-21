"""Read-only title lookup and ROM selection for the favorites editor."""
from ui_text import tr as _tr
import os
from pathlib import Path

from title_metadata import title_key, title_database, load_titles, display_title


def rom_rows(app_dir, system, titles):
    folder = Path(os.path.expandvars(str(system.get('rom_dir', app_dir))))
    if not folder.is_absolute():
        folder = Path(app_dir) / folder
    if not folder.is_dir():
        raise FileNotFoundError(_tr('ROMフォルダーが見つかりません: {v0}', v0=folder))
    extensions = {str(e).casefold() for e in system.get('extensions', ['.zip', '.7z'])}
    paths = folder.rglob('*') if system.get('recursive', True) else folder.iterdir()
    rows = [(display_title(p, titles), str(p.relative_to(folder)), str(p))
            for p in paths if p.suffix.casefold() in extensions and p.is_file()]
    return sorted(rows, key=lambda r: (r[0].casefold(), r[1].casefold()))


def choose_roms(parent, app_dir, system, titles):
    import tkinter as tk
    from tkinter import ttk, messagebox
    try:
        rows = rom_rows(app_dir, system, titles)
    except OSError as exc:
        messagebox.showerror(_tr('ROMを読み込めません'), str(exc), parent=parent)
        return []
    dialog = tk.Toplevel(parent)
    dialog.title(_tr('お気に入りに追加 — {v0}', v0=system.get('name', system['id'])))
    dialog.geometry('950x600')
    dialog.transient(parent)
    frame = ttk.Frame(dialog, padding=12)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=_tr('タイトル・ファイル名で検索（複数選択可）')).pack(anchor='w')
    query = tk.StringVar()
    search = ttk.Entry(frame, textvariable=query)
    search.pack(fill='x', pady=6)
    area = ttk.Frame(frame)
    area.pack(fill='both', expand=True)
    table = ttk.Treeview(area, columns=('title', 'file'), show='headings', selectmode='extended')
    for col, label, width in [('title', _tr('タイトル'), 590), ('file', _tr('ROMファイル'), 290)]:
        table.heading(col, text=label)
        table.column(col, width=width)
    scroll = ttk.Scrollbar(area, command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    table.pack(side='left', fill='both', expand=True)
    scroll.pack(side='right', fill='y')
    status = ttk.Label(frame)
    status.pack(anchor='w', pady=6)
    selected = set()
    result = []
    pending = None

    def remember():
        visible = set(table.get_children())
        selected.difference_update(visible)
        selected.update(table.selection())

    def refresh():
        nonlocal pending
        pending = None
        remember()
        table.delete(*table.get_children())
        words = query.get().casefold().split()
        count = 0
        for i, (title, filename, _) in enumerate(rows):
            if all(w in (title + ' ' + filename).casefold() for w in words):
                iid = str(i)
                table.insert('', 'end', iid=iid, values=(title, filename))
                if iid in selected:
                    table.selection_add(iid)
                count += 1
        status.configure(text=_tr('{v0} / {v1} 件（検索前に選択した項目も保持します）', v0=count, v1=len(rows)))

    def changed(*_):
        nonlocal pending
        if pending is not None:
            dialog.after_cancel(pending)
        pending = dialog.after(180, refresh)

    def close(accept=False):
        if pending is not None:
            dialog.after_cancel(pending)
        if accept:
            remember()
            result.extend(rows[i][2] for i in sorted(map(int, selected)))
        dialog.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill='x')
    ttk.Button(buttons, text=_tr('キャンセル'), command=close).pack(side='right')
    ttk.Button(buttons, text=_tr('選択したROMを追加'), command=lambda: close(True)).pack(side='right', padx=8)
    query.trace_add('write', changed)
    dialog.protocol('WM_DELETE_WINDOW', close)
    refresh()
    search.focus_set()
    dialog.grab_set()
    parent.wait_window(dialog)
    return result
