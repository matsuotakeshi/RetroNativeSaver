"""Exercise the real Tk widgets without displaying a window or changing user files."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk=None


@unittest.skipIf(tk is None,'Tk not installed in this Python runtime')
class FavoriteInputEditorTests(unittest.TestCase):
    def test_sequence_form_add_edit_delete_validation_and_legacy_load(self):
        from favorite_input_editor import InputEditor
        root=tk.Tk();root.withdraw()
        try:
            form=InputEditor(root);form.pack();root.update()
            form.enabled.set(True);form.delay.set('5');form.add_step();root.update()
            self.assertEqual(form.delay.get(),'6');self.assertEqual(form.key.get(),'Start')
            form.key.set('A');form.add_step();root.update()
            form.delay.set('8');form.device.set('キーボード');form.update_keys();form.key.set('Enter')
            value=form.value()
            self.assertEqual([(s['delay_seconds'],s['key']) for s in value],[(5,'Start'),(6,'A'),(8,'Enter')])
            form.load(value);root.update();self.assertEqual(form.value(),value)
            form.table.selection_set('1');root.update();form.delay.set('-1')
            with patch('tkinter.messagebox.showerror') as error:
                form.table.selection_set('2');root.update();error.assert_called_once()
            self.assertEqual(form.current,1)
            form.delay.set('9')
            with self.assertRaises(ValueError):form.value()
            form.remove_step();root.update()
            self.assertEqual([s['key'] for s in form.value()],['Start','Enter'])
            form.remove_step();root.update()
            self.assertIsInstance(form.value(),dict)
            form.remove_step();root.update();self.assertIsNone(form.value())
            form.add_step();root.update();self.assertIsInstance(form.value(),dict)
            form.load(dict(delay_seconds=2,device='keyboard',key='Space'));root.update()
            self.assertEqual(form.value(),dict(delay_seconds=2,device='keyboard',key='Space'))
        finally:root.destroy()

    def test_sequence_add_apply_multiple_roms_and_save_reload(self):
        from favorite_input_editor import InputEditor
        from favorites import show_favorites_editor,load_favorites
        root=tk.Tk();root.withdraw()
        def widgets(parent):
            for child in parent.winfo_children():
                yield child;yield from widgets(child)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);systems=folder/'systems';systems.mkdir()
            (systems/'nes.json').write_text('{"id":"nes","name":"NES"}')
            path=folder/'favorites.json';expected=None
            def drive():
                nonlocal expected
                root.update_idletasks();all_widgets=list(widgets(root))
                form=next(w for w in all_widgets if isinstance(w,InputEditor))
                table=next(w for w in all_widgets if isinstance(w,ttk.Treeview) and w is not form.table)
                buttons={str(w.cget('text')):w for w in all_widgets if isinstance(w,ttk.Button)}
                form.enabled.set(True);form.add_step();root.update()
                form.key.set('A');form.add_step();root.update()
                form.device.set('キーボード');form.update_keys();form.key.set('Space')
                expected=form.value()
                buttons['ROMを追加…'].invoke();root.update();buttons['保存'].invoke()
                self.assertEqual([r['startup_input'] for r in load_favorites(path)['items']],[expected,expected])
                table.selection_set('0','1');root.update()
                form.table.selection_set('2');root.update();form.key.set('Enter')
                expected=form.value();buttons['自動入力を適用'].invoke();root.update();buttons['保存'].invoke()
                self.assertEqual([r['startup_input'] for r in load_favorites(path)['items']],[expected,expected])
                table.selection_set('0');root.update();form.table.selection_set('0');root.update()
                form.key.set('B');buttons['自動入力を適用'].invoke();root.update();buttons['保存'].invoke()
                items=load_favorites(path)['items']
                self.assertEqual(items[0]['startup_input'][0]['key'],'B')
                self.assertEqual(items[1]['startup_input'],expected)
            try:
                with patch.object(tk,'Tk',return_value=root),patch.object(root,'mainloop',side_effect=drive),\
                     patch('favorites.load_titles',return_value={}),\
                     patch('tkinter.filedialog.askopenfilenames',return_value=(str(folder/'one.nes'),str(folder/'two.nes'))),\
                     patch('tkinter.messagebox.showinfo'),patch('tkinter.messagebox.showerror') as error:
                    show_favorites_editor(folder,systems,path)
                error.assert_not_called()
            finally:root.destroy()

    def test_add_edit_remove_save_and_invalid_delay(self):
        from favorite_input_editor import InputEditor
        from favorites import show_favorites_editor,load_favorites
        root=tk.Tk();root.withdraw()
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);systems=folder/'systems';systems.mkdir()
            (systems/'pc88.json').write_text('{"id":"pc88","name":"PC88"}',encoding='utf-8')
            path=folder/'favorites.json'
            first=folder/'one.d88';second=folder/'two.d88'
            def drive():
                root.update_idletasks()
                all_widgets=list(widgets(root))
                form=next(w for w in all_widgets if isinstance(w,InputEditor))
                table=next(w for w in all_widgets if isinstance(w,ttk.Treeview) and w is not form.table)
                buttons={str(w.cget('text')):w for w in all_widgets if isinstance(w,ttk.Button)}
                self.assertLessEqual(form.winfo_reqwidth(),918)
                self.assertIsNone(form.value())
                form.enabled.set(True);form.delay.set('3.5')
                form.device.set('キーボード');form.update_keys()
                self.assertEqual(form.key.get(),'Enter')
                buttons['ROMを追加…'].invoke();root.update()
                buttons['保存'].invoke()
                data=load_favorites(path)
                self.assertEqual(len(data['items']),2)
                self.assertEqual(data['items'][0]['startup_input'],dict(delay_seconds=3.5,device='keyboard',key='Enter'))
                table.selection_set('0','1');root.update()
                self.assertEqual(form.delay.get(),'3.5')
                form.device.set('ゲームボタン');form.update_keys();form.key.set('A');form.delay.set('7')
                buttons['自動入力を適用'].invoke();root.update();buttons['保存'].invoke()
                self.assertEqual([e['startup_input']['key'] for e in load_favorites(path)['items']],['A','A'])
                table.selection_set('0');root.update()
                before=path.read_bytes();form.delay.set('-1')
                buttons['自動入力を適用'].invoke();buttons['保存'].invoke()
                self.assertEqual(path.read_bytes(),before)
                form.enabled.set(False);buttons['自動入力を適用'].invoke();root.update();buttons['保存'].invoke()
                data=load_favorites(path)
                self.assertNotIn('startup_input',data['items'][0])
                self.assertEqual(data['items'][1]['startup_input']['key'],'A')
                self.assertIn('設定なし',table.item('0','values'))
            try:
                with patch.object(tk,'Tk',return_value=root),patch.object(root,'mainloop',side_effect=drive),\
                     patch('favorites.load_titles',return_value={}),\
                     patch('tkinter.filedialog.askopenfilenames',return_value=(str(first),str(second))),\
                     patch('tkinter.messagebox.showinfo'),patch('tkinter.messagebox.showerror') as error:
                    show_favorites_editor(folder,systems,path)
                error.assert_called_once()
            finally:
                root.destroy()


if __name__=='__main__':unittest.main()
