import ast
import ctypes
import io
import json
from pathlib import Path
import tempfile
import contextlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import saver_actions as actions
import saver_controls as ui


def slot(pid, rom='a.zip', ready=True):
    return dict(proc=Mock(pid=pid, poll=Mock(return_value=None)), ready=ready,
                pick=({'id':'mame','name':'MAME Current'},Path(rom)))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.slots = [slot(10),None,slot(12,ready=False),slot(13,'b.zip')]
        self.now = 100.
        self.ui = ui.Selection(self.slots, lambda:self.now)

    def test_first_arrow_wrap_timeout_and_hidden_actions(self):
        self.ui.key(ui.DELETE); self.ui.key(ui.INSERT)
        self.assertIsNone(self.ui.index); self.assertFalse(self.ui.actions)
        self.ui.key(ui.LEFT); self.assertEqual(self.ui.index,0)
        self.ui.key(ui.LEFT); self.assertEqual(self.ui.index,3)
        self.ui.key(ui.RIGHT); self.assertEqual(self.ui.index,0)
        self.now=105.; self.ui.key(ui.INSERT)
        self.assertIsNone(self.ui.index); self.assertFalse(self.ui.actions)
        self.ui.key(ui.RIGHT); self.assertEqual(self.ui.index,0)

    def test_no_ready_tiles_and_replacement_loading(self):
        empty=ui.Selection([None,slot(2,ready=False)],lambda:100.)
        empty.key(ui.RIGHT); self.assertIsNone(empty.index)
        self.ui.key(ui.RIGHT)
        self.slots[0]=slot(20,ready=False)
        self.ui.key(ui.DELETE)
        self.assertFalse(self.ui.actions)
        self.ui.key(ui.RIGHT); self.assertEqual(self.ui.index,3)

    def test_actions_capture_process_and_extend_timeout(self):
        self.ui.key(ui.RIGHT); self.now=104.
        self.ui.key(ui.INSERT); self.assertEqual(self.ui.until,109.)
        self.ui.key(ui.DELETE); self.ui.key(ui.DELETE)
        self.assertEqual(list(self.ui.actions),[(ui.INSERT,0,self.slots[0]),(ui.DELETE,0,self.slots[0])])
        self.slots[0]=slot(20,'other.zip')
        self.assertEqual(self.ui.actions[-1][2]['proc'].pid,10)

    def test_reserved_keys_repeat_and_regular_exit_boundary(self):
        target=Mock()
        for key in ui.KEYS:
            self.assertTrue(ui.handle_message(target,0x100,key,0))
        self.assertEqual(target.key.call_count,7)
        for key in (ui.UP,ui.DOWN,ui.DELETE,ui.INSERT,ui.ENTER):
            self.assertTrue(ui.handle_message(target,0x100,key,1<<30))
        self.assertEqual(target.key.call_count,7)
        self.assertTrue(ui.handle_message(target,0x100,ui.RIGHT,1<<30))
        for msg,key in ((0x104,ui.RIGHT),(0x100,27),(0x201,0),(0x100,65)):
            self.assertFalse(ui.handle_message(target,msg,key,0))
        self.assertFalse(ui.handle_message(None,0x100,ui.DELETE,0))

    def test_forwarded_repeat_suppression_and_window_ownership_lookup(self):
        user=Mock(); user.IsWindow.return_value=True
        control=ui.ForwardKeys(user,lambda:99)
        for key in (ui.UP,ui.DOWN,ui.DELETE,ui.INSERT):
            ui.handle_message(control,0x100,key,1<<30)
        user.PostMessageW.assert_not_called()
        ui.handle_message(control,0x100,ui.DELETE,0)
        user.PostMessageW.assert_called_once_with(99,ui.KEY_MESSAGE,ui.DELETE,0)
        user.IsWindow.return_value=False
        control.key(ui.RIGHT); self.assertEqual(user.PostMessageW.call_count,1)

    def test_actual_wndproc_consumes_only_configured_keys(self):
        source=Path(__file__).with_name('native_saver.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GDIWindow')
        fn=next(n for n in cls.body if getattr(n,'name','')=='_proc')
        ns={}
        for n in tree.body:
            if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id.startswith('WM_') for t in n.targets):
                exec(compile(ast.Module(body=[n],type_ignores=[]),'<constants>','exec'),ns)
        ns['user32']=Mock()
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual proc>','exec'),ns)
        for key in ui.KEYS:
            w=SimpleNamespace(fullscreen=False,preview_mode=False,should_close=False,power_idle=False,
                              saver_controls=Mock(),_note_exit=Mock())
            ns['_proc'](w,123,0x100,key,0)
            self.assertFalse(w.should_close);w.saver_controls.key.assert_called_once_with(key)
        for key in (27,65):
            w=SimpleNamespace(fullscreen=False,preview_mode=False,should_close=False,power_idle=False,
                              saver_controls=Mock(),_note_exit=Mock())
            ns['_proc'](w,123,0x100,key,0)
            self.assertTrue(w.should_close);w.saver_controls.key.assert_not_called()

    def test_up_without_selection_including_no_ready_tiles_coalesces(self):
        for records in (self.slots, [None,slot(2,ready=False)], [None,None]):
            control=ui.Selection(records,lambda:100.)
            control.key(ui.UP);control.key(ui.UP)
            self.assertEqual(list(control.actions),[(ui.UP,None,None)])
            self.assertIsNone(control.index)
            control.key(ui.INSERT);control.key(ui.DELETE)
            self.assertEqual(list(control.actions),[(ui.UP,None,None)])

    def test_up_clears_selection_without_discarding_prior_registration(self):
        self.ui.key(ui.RIGHT);self.ui.key(ui.INSERT);self.ui.key(ui.UP)
        self.assertEqual(list(self.ui.actions),[(ui.INSERT,0,self.slots[0]),(ui.UP,None,None)])
        self.assertIsNone(self.ui.visible(100.))
        self.assertEqual(self.ui.until,0.)

    def test_controls_remain_opt_in_and_independent_only(self):
        for cfg in ({},{'saver_controls_enabled':True},{'independent_slots_enabled':True},
                    {'saver_controls_enabled':False,'independent_slots_enabled':True}):
            self.assertFalse(ui.enabled(cfg))
        self.assertTrue(ui.enabled({'saver_controls_enabled':True,'independent_slots_enabled':True}))

    def test_down_without_selection_including_loading_and_empty_coalesces(self):
        for records in (self.slots,[slot(20,ready=False),None],[None,None],[]):
            control=ui.Selection(records,lambda:100.)
            control.key(ui.DOWN);control.key(ui.DOWN)
            self.assertEqual(list(control.actions),[(ui.DOWN,None,None)])
            self.assertIsNone(control.index)
            control.key(ui.INSERT);control.key(ui.DELETE)
            self.assertEqual(len(control.actions),1)

    def test_down_clears_selection_and_preserves_prior_insert(self):
        self.ui.key(ui.RIGHT);self.ui.key(ui.INSERT);self.ui.key(ui.DOWN)
        self.assertEqual(list(self.ui.actions),[(ui.INSERT,0,self.slots[0]),(ui.DOWN,None,None)])
        self.assertIsNone(self.ui.index);self.assertEqual(self.ui.until,0.)


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.black=self.root/'black.json';self.white=self.root/'white.json';self.seed=self.root/'seed.json'
        self.favorite=self.root/'favorites.json'
    def write(self,path,data):
        path.write_text(json.dumps(data),encoding='utf-8');return path.read_bytes()
    def read(self,path):return json.loads(path.read_text(encoding='utf-8'))
    def blacklist(self):return actions.blacklist_rom(self.black,self.white,self.seed,'MAME Current','a.zip')

    def test_blacklist_preserves_evidence_unknown_fields_and_white_others(self):
        original=self.write(self.black,{'version':1,'extra':'keep','systems':{'mame current':{
            'A.ZIP':{'failure_sessions':4,'last_failure_kind':'crash','custom':'keep'},
            'b.zip':{'blacklisted':True}}}})
        white=self.write(self.white,{'extra':'keep','systems':{'MAME CURRENT':['a.zip','B.ZIP'],'Other':['a.zip']}})
        black,allowed=self.blacklist()
        entry=black['systems']['mame current']['A.ZIP']
        self.assertTrue(entry['blacklisted']);self.assertTrue(entry['manual_blacklisted'])
        self.assertEqual(entry['failure_sessions'],4);self.assertEqual(entry['last_failure_kind'],'crash')
        self.assertEqual(entry['custom'],'keep');self.assertEqual(black['extra'],'keep')
        self.assertEqual(allowed,{'MAME CURRENT':{'B.ZIP'},'Other':{'a.zip'}})
        self.assertEqual(self.read(self.white)['extra'],'keep')
        self.assertIn(original,[p.read_bytes() for p in self.root.glob('black.json.*.bak')])
        self.assertIn(white,[p.read_bytes() for p in self.root.glob('white.json.*.bak')])

    def test_new_manual_entry_is_not_a_crash_and_seed_is_respected(self):
        seed=self.write(self.seed,{'systems':{'MAME Current':['a.zip','b.zip']}})
        black,white=self.blacklist()
        self.assertEqual(black['systems']['MAME Current']['a.zip']['failure_sessions'],0)
        self.assertEqual(white,{'MAME Current':{'b.zip'}})
        self.assertEqual(self.seed.read_bytes(),seed)

    def test_invalid_black_or_white_never_replaced(self):
        for bad in (self.black,self.white):
            self.write(self.black,{'systems':{}});self.write(self.white,{'systems':{}})
            bad.write_bytes(b'{broken')
            old=(self.black.read_bytes(),self.white.read_bytes())
            with self.assertRaises(ValueError):self.blacklist()
            self.assertEqual((self.black.read_bytes(),self.white.read_bytes()),old)

    def test_atomic_failure_and_concurrent_edit_preserve_file(self):
        original=self.write(self.black,{'systems':{}})
        with patch.object(actions.os,'replace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.blacklist()
        self.assertEqual(self.black.read_bytes(),original)
        self.assertFalse(list(self.root.glob('*.tmp')))
        self.write(self.black,{'systems':{},'external':'edit'})
        with self.assertRaises(RuntimeError):actions.save_checked(self.black,{'systems':{}},original)
        self.assertEqual(self.read(self.black)['external'],'edit')

    def test_white_write_failure_keeps_whitelist_override(self):
        white=self.write(self.white,{'systems':{'MAME Current':['a.zip']}})
        original=actions.save_checked
        def save(path,*args):
            if path==self.white:raise OSError('write denied')
            return original(path,*args)
        with patch.object(actions,'save_checked',side_effect=save):
            with self.assertRaises(OSError):self.blacklist()
        self.assertEqual(self.white.read_bytes(),white)
        from rom_list_policy import _persistent_blacklisted_roms, _apply_persistent_whitelist
        blocked,_=_apply_persistent_whitelist(_persistent_blacklisted_roms(self.read(self.black)),{'MAME Current':{'a.zip'}})
        self.assertEqual(blocked,{})

    def test_favorite_duplicate_basename_keeps_auto_input_and_disabled_flag(self):
        system={'id':'mame'};rom=self.root/'a.zip';catalog={'mame':[rom]}
        value={'enabled':False,'custom':1,'items':[{'system':'MAME','rom':'A.ZIP',
            'startup_input':{'delay_seconds':5,'device':'joypad','key':'Start'},'custom':2}]}
        raw=self.write(self.favorite,value)
        self.assertFalse(actions.add_favorite(self.favorite,system,rom,catalog))
        self.assertEqual(self.favorite.read_bytes(),raw)
        other=self.root/'b.zip'
        self.assertTrue(actions.add_favorite(self.favorite,system,other,{'mame':[rom,other]}))
        saved=self.read(self.favorite)
        self.assertFalse(saved['enabled']);self.assertEqual(saved['items'][0],value['items'][0])
        self.assertEqual(saved['custom'],1);self.assertEqual(len(saved['items']),2)

    def test_favorite_ambiguous_basename_adds_unambiguous_full_path(self):
        a=self.root/'one/a.zip';b=self.root/'two/a.zip'
        self.write(self.favorite,{'items':[{'system':'mame','rom':'a.zip'}]})
        self.assertTrue(actions.add_favorite(self.favorite,{'id':'mame'},b,{'mame':[a,b]}))
        self.assertEqual(self.read(self.favorite)['items'][-1]['rom'],str(b.resolve()))
        self.assertFalse(actions.add_favorite(self.favorite,{'id':'mame'},b,{'mame':[a,b]}))

    def test_favorite_corruption_and_io_failure_do_not_erase_data(self):
        self.favorite.write_bytes(b'{bad')
        with self.assertRaises(ValueError):actions.add_favorite(self.favorite,{'id':'mame'},Path('a.zip'),{})
        self.assertEqual(self.favorite.read_bytes(),b'{bad')
        raw=self.write(self.favorite,{'items':[]})
        with patch.object(actions.os,'replace',side_effect=OSError('write denied')):
            with self.assertRaises(OSError):actions.add_favorite(self.favorite,{'id':'mame'},Path('a.zip'),{})
        self.assertEqual(self.favorite.read_bytes(),raw)

    def test_supervisor_refresh_keeps_manual_block_across_restart_and_failure_save(self):
        black,_=self.blacklist()
        safety=SimpleNamespace(persistent_rom_blacklist_path=self.black,
            persistent_rom_whitelist_path=self.white,persistent_rom_whitelist_seed_path=self.seed,
            persistent_rom_whitelist_enabled=True,persistent_rom_blacklist_enabled=True,
            persistent_rom_state={'systems':{}},session_quarantine={'Other':{'crash.zip'}})
        actions.refresh_safety(safety)
        self.assertEqual(safety.persistent_rom_state,black)
        self.assertEqual(safety.session_quarantine,{'Other':{'crash.zip'}})
        from rom_state_store import _record_persistent_rom_failure
        _record_persistent_rom_failure(safety.persistent_rom_state,self.black,'session',2,'Other','b.zip','RUN_ENTER','crash')
        self.assertTrue(self.read(self.black)['systems']['MAME Current']['a.zip']['blacklisted'])

    def test_failed_parent_refresh_keeps_session_containment_without_stale_save(self):
        self.black.write_bytes(b'{unreadable')
        safety=SimpleNamespace(persistent_rom_blacklist_path=self.black,
            persistent_rom_blacklist_enabled=True,persistent_rom_state={'systems':{'keep':{}}})
        def record(snapshot,watchdog):
            self.assertFalse(safety.persistent_rom_blacklist_enabled)
            self.assertEqual(snapshot,{'phase':'RUN_ENTER'})
            self.assertTrue(watchdog)
        safety.record_runtime_failure=Mock(side_effect=record)
        with contextlib.redirect_stdout(io.StringIO()):
            safety.persistent_rom_whitelist_path = self.white
            actions.record_failure_with_fresh_lists(safety,{'phase':'RUN_ENTER'},True)
        safety.record_runtime_failure.assert_called_once()
        self.assertTrue(safety.persistent_rom_blacklist_enabled)
        self.assertEqual(safety.persistent_rom_state,{'systems':{'keep':{}}})
        self.assertEqual(self.black.read_bytes(),b'{unreadable')


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.slots=[slot(10),slot(11,'b.zip')]
        self.control=ui.Selection(self.slots,lambda:100.)
        self.control.publish=Mock()
        self.control.key(ui.RIGHT)
        self.banned=set();self.next_try=[9.,9.];self.state={'systems':{}};self.white={}
        self.catalogs={'mame':[Path('a.zip'),Path('b.zip'),Path('dir/A.ZIP')]}
        self.disposed=[]
    def dispose(self,index):self.disposed.append(index);self.slots[index]=None
    def run_actions(self,dispose=None,cfg=None):
        with contextlib.redirect_stdout(io.StringIO()):
            ui.process_actions(self.control,self.slots,cfg or {},self.catalogs,'favorites.json',
                'black.json',self.state,self.white,lambda value,default:Path(default),self.banned,
                dispose or self.dispose,self.next_try,100.)

    def test_delete_replaces_only_selected_after_save_with_ordinary_basename_exclusion(self):
        self.control.key(ui.RIGHT)  # ordinary slot; slot 0 now removes favorites
        self.control.key(ui.DELETE)
        with patch.object(actions,'blacklist_rom',return_value=({'systems':{'new':{}}},{'white':{'keep'}})) as save:
            self.run_actions()
        save.assert_called_once();self.assertEqual(self.disposed,[1]);self.assertIsNotNone(self.slots[0])
        self.assertFalse(self.banned)
        self.assertEqual(self.catalogs,{'mame':[Path('a.zip'),Path('dir/A.ZIP')]})
        self.assertEqual(self.next_try,[9.,100.]);self.assertEqual(self.state,{'systems':{'new':{}}})
        self.assertEqual(self.control.status,ui.BLOCKED)

    def test_save_failure_disabled_blacklist_never_kills_or_bans(self):
        self.control.key(ui.RIGHT)
        for cfg in ({},{'persistent_rom_blacklist_enabled':False}):
            self.control.key(ui.DELETE)
            with patch.object(actions,'blacklist_rom',side_effect=OSError('disk full')):
                self.run_actions(cfg=cfg)
            self.assertFalse(self.disposed);self.assertFalse(self.banned);self.assertEqual(self.control.status,ui.ERROR)

    def test_exit_or_pid_replacement_drops_stale_delete(self):
        self.control.key(ui.DELETE);self.slots[0]=slot(10,'replacement.zip')  # even PID reuse
        with patch.object(actions,'blacklist_rom') as save:self.run_actions();save.assert_not_called()
        self.control.key(ui.DELETE);self.slots[0]['proc'].poll.return_value=75
        with patch.object(actions,'blacklist_rom') as save:self.run_actions();save.assert_not_called()
        self.assertFalse(self.disposed)

    def test_insert_keeps_tile_and_delete_cleanup_failure_propagates(self):
        self.control.key(ui.INSERT)
        with patch.object(actions,'add_favorite',return_value=False):self.run_actions()
        self.assertFalse(self.disposed);self.assertEqual(self.control.status,ui.EXISTS)
        self.control.key(ui.RIGHT)
        self.control.key(ui.DELETE)
        with patch.object(actions,'blacklist_rom',return_value=({'systems':{}},{})):
            with self.assertRaises(TimeoutError):self.run_actions(dispose=Mock(side_effect=TimeoutError('still alive')))
        self.assertEqual(self.next_try,[9.,9.])

    def test_session_failure_filters_favorite_and_resource_limits_remain(self):
        from independent_slots import select_slot
        system={'id':'mame','name':'MAME Current','resource_group':'heavy_cd','resource_weight':1,'max_concurrent':2}
        cfg={'resource_groups':{'heavy_cd':{'max_weight':1}}}
        blocked={('mame','a.zip')}
        catalogs={'mame':[Path('a.zip'),Path('b.zip')]}
        pick=select_slot(0,[system],catalogs,cfg,[],[(system,Path('a.zip'))],blocked,set())
        self.assertEqual(pick[1],Path('b.zip'))
        self.assertIsNone(select_slot(1,[system],catalogs,cfg,[pick],[],blocked,set()))

    def test_up_disposes_ready_loading_and_empty_tiles_without_saving_or_banning(self):
        self.slots.extend([slot(12,ready=False),None])
        self.next_try[:]=[101.,102.,103.,104.]
        self.banned.add(('mame','past_failure.zip'))
        self.state['systems']['prior']={'keep':True};self.white['prior']={'keep'}
        self.control.key(ui.UP)
        with patch.object(actions,'blacklist_rom') as black, patch.object(actions,'add_favorite') as favorite:
            self.run_actions()
            black.assert_not_called();favorite.assert_not_called()
        self.assertEqual(self.disposed,[0,1,2,3])
        self.assertEqual(self.slots,[None]*4);self.assertEqual(self.next_try,[100.]*4)
        self.assertEqual(self.banned,{('mame','past_failure.zip')})
        self.assertEqual(self.state,{'systems':{'prior':{'keep':True}}})
        self.assertEqual(self.white,{'prior':{'keep'}})
        self.assertIsNone(self.control.index)

    def test_up_drops_stale_tile_action_and_preserves_earlier_insert(self):
        self.control.key(ui.INSERT);self.control.key(ui.UP)
        self.control.key(ui.RIGHT);self.control.key(ui.DELETE)
        with patch.object(actions,'add_favorite',return_value=True) as favorite, patch.object(actions,'blacklist_rom') as black:
            self.run_actions()
            favorite.assert_called_once();black.assert_not_called()
        self.assertEqual(self.disposed,[0,1]);self.assertIsNone(self.control.index)

    def test_up_cleanup_failure_aborts_and_never_releases_failed_slot(self):
        original=self.slots[1]
        def dispose(index):
            if index==1:raise TimeoutError('still alive')
            self.dispose(index)
        self.control.key(ui.UP)
        with self.assertRaises(TimeoutError):self.run_actions(dispose=dispose)
        self.assertIsNone(self.slots[0]);self.assertIs(self.slots[1],original)
        self.assertEqual(self.next_try,[9.,9.]);self.assertFalse(self.banned)

    def test_up_refill_keeps_favorite_slot_and_heavy_limit(self):
        from independent_slots import select_slot
        system={'id':'mame','name':'MAME Current','resource_group':'heavy_cd','resource_weight':1,'max_concurrent':2}
        cfg={'resource_groups':{'heavy_cd':{'max_weight':1}}}
        self.control.key(ui.UP);self.run_actions()
        favorite=(system,Path('b.zip'))
        first=select_slot(0,[system],self.catalogs,cfg,[],[favorite],self.banned,set())
        self.assertEqual(first,favorite)
        self.assertIsNone(select_slot(1,[system],self.catalogs,cfg,[first],[favorite],self.banned,set()))

    def test_down_replaces_only_first_ready_or_loading_tile_without_saving(self):
        for ready in (True,False):
            self.slots[0]=slot(10,ready=ready)
            other=self.slots[1];self.disposed.clear();self.next_try[:]=[110.,120.]
            self.banned.add(('mame','failed.zip'))
            self.state['systems']['prior']={'keep':True};self.white['prior']={'keep'}
            self.control.key(ui.DOWN)
            with patch.object(actions,'blacklist_rom') as black,patch.object(actions,'add_favorite') as favorite:
                self.run_actions();black.assert_not_called();favorite.assert_not_called()
            self.assertEqual(self.disposed,[0]);self.assertIsNone(self.slots[0]);self.assertIs(self.slots[1],other)
            self.assertEqual(self.next_try,[100.,120.])
            self.assertEqual(self.control.favorite_skip,('mame','a.zip'))
            self.assertEqual(self.banned,{('mame','failed.zip')})
            self.assertEqual(self.state,{'systems':{'prior':{'keep':True}}})
            self.assertEqual(self.white,{'prior':{'keep'}})
            self.assertIsNone(self.control.index)

    def test_down_empty_slot_retries_now_and_keeps_pending_skip(self):
        self.slots[0]=None;other=self.slots[1]
        self.control.favorite_skip=('mame','a.zip')
        self.control.key(ui.DOWN);self.run_actions()
        self.assertEqual(self.next_try,[100.,9.]);self.assertIs(self.slots[1],other)
        self.assertEqual(self.control.favorite_skip,('mame','a.zip'))
        self.slots.clear();self.next_try.clear()
        self.control.key(ui.DOWN);self.run_actions()  # no favorite tile configured

    def test_down_cleanup_failure_keeps_reservation_and_retry_state(self):
        original=self.slots[:]
        self.control.key(ui.DOWN)
        with self.assertRaises(TimeoutError):self.run_actions(dispose=Mock(side_effect=TimeoutError('alive')))
        self.assertEqual(self.slots,original);self.assertEqual(self.next_try,[9.,9.])
        self.assertIsNone(self.control.favorite_skip);self.assertFalse(self.banned)

    def test_down_drops_stale_delete_and_preserves_prior_insert(self):
        self.control.key(ui.INSERT);self.control.key(ui.DOWN)
        self.control.key(ui.RIGHT);self.control.key(ui.DELETE)
        with patch.object(actions,'add_favorite',return_value=True) as favorite,patch.object(actions,'blacklist_rom') as black:
            self.run_actions();favorite.assert_called_once();black.assert_not_called()
        self.assertEqual(self.disposed,[0]);self.assertIsNotNone(self.slots[1])

    def test_up_clears_pending_manual_favorite_skip(self):
        self.control.key(ui.DOWN);self.control.key(ui.UP);self.run_actions()
        self.assertIsNone(self.control.favorite_skip)
        self.assertEqual(self.slots,[None,None])


class FavoriteAdvanceTests(unittest.TestCase):
    def setUp(self):
        self.system=dict(id='a',name='A',max_concurrent=2,resource_group='heavy_cd',resource_weight=1)
        self.a,self.b=Path('a.zip'),Path('b.zip')
        self.catalogs={'a':[self.a,self.b]}
        self.cfg={'resource_groups':{'heavy_cd':{'max_weight':2}}}
        self.favorites=[(self.system,self.a),(self.system,self.b)]

    def select(self,**kw):
        from independent_slots import select_slot
        options=dict(index=0,systems=[self.system],catalogs=self.catalogs,cfg=self.cfg,
                     occupied=[],favorites=self.favorites,banned=set(),suspended=set(),
                     favorite_skip=('a',str(self.a)),rng=SimpleNamespace(choice=lambda pool:pool[0]))
        options.update(kw)
        return select_slot(**options)

    def test_another_favorite_preferred_only_during_manual_skip(self):
        self.assertEqual(self.select()[1],self.b)
        self.assertEqual(self.select(favorite_skip=None)[1],self.a)
        # A single eligible favorite may restart; skip is not a blacklist.
        self.assertEqual(self.select(favorites=self.favorites[:1])[1],self.a)
        # Ordinary tiles do not use the manual favorite preference.
        self.assertEqual(self.select(index=1,favorites=[])[1],self.a)

    def test_blacklisted_favorite_catalog_and_automatic_input_are_retained(self):
        favored=dict(self.system,_favorite_startup_input={'delay_seconds':5.,'device':'joypad','key':'Start'})
        picked=self.select(catalogs={'a':[]},favorite_catalogs=self.catalogs,
                           favorites=[self.favorites[0],(favored,self.b)])
        self.assertEqual(picked,(favored,self.b))

    def test_manual_skip_never_bypasses_quarantine_missing_disabled_or_suspended(self):
        self.assertEqual(self.select(banned={('a',str(self.b))})[1],self.a)
        self.assertEqual(self.select(favorite_catalogs={'a':[self.a]})[1],self.a)
        self.assertIsNone(self.select(suspended={'A'}))
        self.system['enabled']=False
        self.assertIsNone(self.select())

    def test_concurrency_and_heavy_limits_override_different_favorite_preference(self):
        large=dict(id='large',name='Large',max_concurrent=1,resource_group='heavy_cd',resource_weight=2)
        catalogs=dict(self.catalogs,large=[Path('large.zip')])
        favorites=self.favorites[:1]+[(large,Path('large.zip'))]
        # Another live tile uses 1; the larger favorite cannot replace the old title.
        self.assertEqual(self.select(systems=[self.system,large],catalogs=catalogs,favorites=favorites,
                                     occupied=[(self.system,self.b)])[1],self.a)
        self.assertIsNone(self.select(occupied=[(self.system,self.b)]*2))
        self.system['max_concurrent']=1
        self.assertIsNone(self.select(occupied=[(self.system,self.b)]))


if __name__=='__main__':unittest.main()
