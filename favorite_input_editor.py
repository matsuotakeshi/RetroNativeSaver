"""Favorite input sequence form, shared by additions and selected-entry updates."""
from ui_text import tr as _tr
import tkinter as tk
from tkinter import ttk, messagebox
from favorite_input import KEYS, validate_input


class InputEditor(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text=_tr('このROMの自動入力'), padding=8)
        self.enabled = tk.BooleanVar(value=False)
        self.delay = tk.StringVar(value='5')
        self.device = tk.StringVar(value=_tr('ゲームボタン'))
        self.key = tk.StringVar(value='Start')
        self.steps, self.current = [], None
        ttk.Checkbutton(self, text=_tr('有効'), variable=self.enabled).grid(row=0,column=0,sticky='w')
        ttk.Label(self,text=_tr('開始からの秒数を小さい順に設定します。例：5秒 Start → 6秒 A → 8秒 Enter')).grid(row=0,column=1,columnspan=6,sticky='w')
        area = ttk.Frame(self)
        area.grid(row=1,column=0,columnspan=7,sticky='ew',pady=5)
        self.table = ttk.Treeview(area, columns=('time','device','key'), show='headings',selectmode='browse',height=3)
        for name, label, width in (('time',_tr('開始からの秒数'),145),('device',_tr('入力種類'),150),('key',_tr('キー'),180)):
            self.table.heading(name,text=label)
            self.table.column(name,width=width)
        scroll = ttk.Scrollbar(area, orient='vertical',command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        ttk.Label(self, text=_tr('選択した入力：開始から')).grid(row=2,column=0,columnspan=2,sticky='w')
        ttk.Spinbox(self, from_=0, to=86400, increment=.5,textvariable=self.delay,width=9).grid(row=2,column=2,padx=4)
        ttk.Label(self,text=_tr('秒後に')).grid(row=2,column=3)
        self.device_box = ttk.Combobox(self,textvariable=self.device,state='readonly',
                                      values=(_tr('ゲームボタン'),_tr('キーボード')),width=14)
        self.device_box.grid(row=2,column=4,padx=4)
        self.key_box = ttk.Combobox(self,textvariable=self.key,state='readonly',width=16)
        self.key_box.grid(row=2,column=5,padx=4)
        ttk.Label(self,text=_tr('を1回押す')).grid(row=2,column=6)
        buttons = ttk.Frame(self)
        buttons.grid(row=3,column=0,columnspan=7,sticky='w',pady=5)
        ttk.Button(buttons,text=_tr('入力を追加'),command=self.add_step).pack(side='left')
        ttk.Button(buttons,text=_tr('入力を削除'),command=self.remove_step).pack(side='left',padx=6)
        ttk.Label(buttons,text=_tr('追加時は最後の入力を1秒後に繰り返します。各行で変更できます。')).pack(side='left')
        ttk.Label(self,text=_tr('追加するROMに適用します。登録済みの項目は選択して「自動入力を適用」→「保存」を押してください。')).grid(row=4,column=0,columnspan=7,sticky='w')
        ttk.Label(self,text=_tr('通常枠でも有効です。既定の自動Start入力より優先します。同時刻は1つずつ押して離します。')).grid(row=5,column=0,columnspan=7,sticky='w')
        self.columnconfigure(1,weight=1)
        self.device_box.bind('<<ComboboxSelected>>',lambda event:self.update_keys())
        self.table.bind('<<TreeviewSelect>>',self.select_step)
        self.load(None)

    def update_keys(self):
        device = 'joypad' if self.device.get() == _tr('ゲームボタン') else 'keyboard'
        preferred = ('Start','A','B','X','Y','Select') if device == 'joypad' else ('Enter','Space','Escape','Tab')
        values = list(preferred) + [key for key in KEYS[device] if key not in preferred]
        self.key_box.configure(values=values)
        if self.key.get() not in values:
            self.key.set(values[0])

    def field_value(self):
        try:
            delay = float(self.delay.get())
        except ValueError:
            raise ValueError(_tr('入力までの秒数を数値で入力してください。')) from None
        return validate_input(dict(delay_seconds=delay,
            device='joypad' if self.device.get() == _tr('ゲームボタン') else 'keyboard',key=self.key.get()))

    @staticmethod
    def row(value):
        return (_tr('{v0:g}秒', v0=value['delay_seconds']), _tr('ゲームボタン') if value['device']=='joypad' else _tr('キーボード'), value['key'])

    def commit_step(self):
        if self.current is not None:
            value = self.field_value()
            self.steps[self.current] = value
            self.table.item(str(self.current),values=self.row(value))

    def show_step(self, index):
        self.current = index
        if index is None:
            return
        value = self.steps[index]
        self.delay.set(f"{value['delay_seconds']:g}")
        self.device.set(_tr('ゲームボタン') if value['device']=='joypad' else _tr('キーボード'))
        self.update_keys();self.key.set(value['key'])
        self.table.selection_set(str(index));self.table.see(str(index))

    def refresh(self, index):
        self.current = None
        self.table.delete(*self.table.get_children())
        for i, value in enumerate(self.steps):
            self.table.insert('', 'end',iid=str(i),values=self.row(value))
        self.show_step(index)

    def select_step(self, event=None):
        selection = self.table.selection()
        if not selection or int(selection[0]) == self.current:
            return
        index = int(selection[0])
        try:
            self.commit_step()
        except ValueError as exc:
            messagebox.showerror(_tr('入力の設定を確認してください'),str(exc),parent=self)
            self.table.selection_set(str(self.current))
            return
        self.show_step(index)

    def add_step(self):
        try:
            self.commit_step()
            value = dict(self.steps[-1],delay_seconds=self.steps[-1]['delay_seconds']+1) if self.steps else self.field_value()
            validate_input(self.steps+[value])
        except ValueError as exc:
            messagebox.showerror(_tr('入力の設定を確認してください'),str(exc),parent=self)
            return
        self.steps.append(value);self.enabled.set(True)
        self.refresh(len(self.steps)-1)

    def remove_step(self):
        if self.current is None:
            return
        index = self.current
        del self.steps[index]
        if not self.steps:
            self.enabled.set(False)
        self.refresh(min(index,len(self.steps)-1) if self.steps else None)

    def value(self):
        if not self.enabled.get():
            return None
        self.commit_step()
        # A single step keeps the original JSON object format.
        return validate_input(self.steps[0] if len(self.steps)==1 else self.steps)

    def load(self, value):
        self.enabled.set(value is not None)
        value = validate_input(value) if value is not None else dict(delay_seconds=5,device='joypad',key='Start')
        self.steps = value if isinstance(value,list) else [value]
        self.refresh(0)
