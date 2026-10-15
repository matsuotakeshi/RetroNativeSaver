import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import saver_actions as actions
import saver_controls as ui
from favorites import load_favorites, favorite_candidates


class FavoriteRemoveTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.path=self.root/'favorites.json'
        self.system={'id':'mame','name':'MAME Current'}
        self.a=self.root/'a.zip';self.b=self.root/'b.zip'
        self.catalogs={'mame':[self.a,self.b]}

    def write(self,data):
        self.path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        return self.path.read_bytes()

    def remove(self):return actions.remove_favorite(self.path,self.system,self.a,self.catalogs)

    def test_all_matching_aliases_removed_other_entries_and_unknown_fields_preserved(self):
        other={'system':'mame','rom':str(self.b),'custom':9,
               'startup_input':{'delay_seconds':8,'device':'keyboard','key':'Enter'}}
        different_system={'system':'nes','rom':'a.zip','note':'keep'}
        value={'enabled':False,'custom':{'keep':1},'items':[
            {'system':'MAME','rom':'A.ZIP','extra':1},
            {'system':' mame ','rom':str(self.a).upper().replace('\\','/')},
            {'system':'mame','rom':str(self.a)},other,different_system]}
        raw=self.write(value)
        self.assertTrue(self.remove())
        expected=dict(value,items=[other,different_system])
        self.assertEqual(json.loads(self.path.read_bytes()),expected)
        self.assertIn(raw,[p.read_bytes() for p in self.root.glob('*.bak')])
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_last_favorite_keeps_valid_empty_list_and_flags(self):
        self.write({'enabled':True,'items':[{'system':'mame','rom':'a.zip'}],'extra':'keep'})
        self.assertTrue(self.remove());self.assertEqual(load_favorites(self.path),{'enabled':True,'items':[]})
        self.assertEqual(json.loads(self.path.read_bytes())['extra'],'keep')

    def test_missing_or_already_absent_never_creates_or_rewrites_file(self):
        self.assertFalse(self.remove());self.assertFalse(self.path.exists())
        raw=self.write({'items':[{'system':'mame','rom':'b.zip'}]})
        self.assertFalse(self.remove());self.assertEqual(self.path.read_bytes(),raw)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_ambiguous_basename_and_other_same_named_path_are_not_deleted(self):
        other=self.root/'other/a.zip';self.catalogs['mame'].append(other)
        kept=[{'system':'mame','rom':'a.zip'},{'system':'mame','rom':str(other)}]
        self.write({'items':kept+[{'system':'mame','rom':str(self.a)}]})
        self.assertTrue(self.remove());self.assertEqual(json.loads(self.path.read_bytes())['items'],kept)

    def test_canonical_alias_uses_runtime_matching(self):
        self.write({'items':[{'system':'mame','rom':'Z:/alias/a.zip'}]})
        def canonical(_,path):
            return 'same' if str(path).replace('\\','/').casefold().endswith('/a.zip') else 'other'
        with patch('catalog_paths.CatalogPaths.canonical',canonical):self.assertTrue(self.remove())

    def test_corrupt_data_and_write_error_preserve_original(self):
        for raw in (b'{bad',b'{"items":null}',b'{"items":[{"system":"mame"}]}'):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):self.remove()
            self.assertEqual(self.path.read_bytes(),raw)
        raw=self.write({'items':[{'system':'mame','rom':'a.zip'}]})
        with patch.object(actions.os,'replace',side_effect=OSError('denied')):
            with self.assertRaises(OSError):self.remove()
        self.assertEqual(self.path.read_bytes(),raw);self.assertFalse(list(self.root.glob('*.tmp')))

    def test_external_edit_detected_before_commit(self):
        self.write({'items':[{'system':'mame','rom':'a.zip'}]})
        original=actions.save_checked
        def changed(path,data,raw):
            self.write({'items':[{'system':'mame','rom':'b.zip'}],'external':True})
            return original(path,data,raw)
        with patch.object(actions,'save_checked',side_effect=changed):
            with self.assertRaises(RuntimeError):self.remove()
        self.assertTrue(json.loads(self.path.read_bytes())['external'])

    def action(self,slots,control,next_try,dispose,state,white,catalogs,banned):
        with contextlib.redirect_stdout(io.StringIO()):
            ui.process_actions(control,slots,{'persistent_rom_blacklist_enabled':False},catalogs,
                self.path,self.root/'black.json',state,white,lambda v,d:self.root/d,banned,
                dispose,next_try,100.,favorite_catalogs=self.catalogs)

    def setup_action(self):
        record=dict(ready=True,proc=Mock(poll=Mock(return_value=None)),pick=(self.system,self.a))
        other=dict(ready=True,proc=Mock(poll=Mock(return_value=None)),pick=(self.system,self.b))
        slots=[record,other];control=ui.Selection(slots,lambda:100.);control.publish=Mock()
        control.key(ui.RIGHT);control.key(ui.DELETE)
        return slots,control,[9.,9.]

    def test_favorite_delete_commits_before_replacing_only_first_keeps_all_safety_lists(self):
        self.write({'items':[{'system':'mame','rom':'a.zip'},{'system':'mame','rom':'b.zip'}]})
        slots,control,next_try=self.setup_action();other=slots[1]
        state={'systems':{'MAME Current':{'a.zip':{'blacklisted':True}}}}
        white={'MAME Current':{'a.zip'}};banned={('other','failed')};catalogs={'mame':[self.b]}
        before=copy.deepcopy((state,white,banned,catalogs,self.catalogs))
        def dispose(i):
            self.assertEqual(i,0)
            self.assertEqual([r for _,r in favorite_candidates([self.system],self.catalogs,load_favorites(self.path))],[self.b])
            slots[i]=None
        with patch.object(actions,'blacklist_rom') as black:
            self.action(slots,control,next_try,dispose,state,white,catalogs,banned);black.assert_not_called()
        self.assertIs(slots[1],other);self.assertIsNone(slots[0]);self.assertEqual(next_try,[100.,9.])
        self.assertEqual((state,white,banned,catalogs,self.catalogs),before)
        self.assertEqual(control.status,ui.REMOVED)
        from independent_slots import _refresh_scheduler_favorites
        _,matched=_refresh_scheduler_favorites(self.path,object(),[],[self.system],self.catalogs)
        self.assertEqual([r for _,r in matched],[self.b])

    def test_remove_failure_keeps_tile_and_retry_state_without_blacklist_fallback(self):
        self.path.write_bytes(b'{bad');slots,control,next_try=self.setup_action();dispose=Mock()
        with patch.object(actions,'blacklist_rom') as black:
            self.action(slots,control,next_try,dispose,{}, {},self.catalogs,set());black.assert_not_called()
        dispose.assert_not_called();self.assertEqual(control.status,ui.ERROR);self.assertEqual(next_try,[9.,9.])

    def test_already_removed_still_replaces_without_touching_blacklist(self):
        slots,control,next_try=self.setup_action()
        with patch.object(actions,'blacklist_rom') as black:
            self.action(slots,control,next_try,lambda i:slots.__setitem__(i,None),{}, {},self.catalogs,set())
            black.assert_not_called()
        self.assertIsNone(slots[0]);self.assertFalse(self.path.exists())

    def test_cleanup_failure_preserves_reservation_after_successful_remove(self):
        self.write({'items':[{'system':'mame','rom':'a.zip'}]})
        slots,control,next_try=self.setup_action();first=slots[0]
        with self.assertRaises(TimeoutError):
            self.action(slots,control,next_try,Mock(side_effect=TimeoutError('alive')),{}, {},self.catalogs,set())
        self.assertIs(slots[0],first);self.assertEqual(next_try,[9.,9.])
        self.assertEqual(load_favorites(self.path)['items'],[])


if __name__=='__main__':unittest.main()
