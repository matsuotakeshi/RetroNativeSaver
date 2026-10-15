import contextlib
import ctypes
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import retroarch_launch as ra
import saver_controls as ui


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root/'Retro Arch'
        (self.install/'cores').mkdir(parents=True)
        self.exe = self.install/'retroarch.exe';self.exe.touch()
        self.core = self.install/'cores/core.dll';self.core.touch()
        self.rom = self.root/'日本語 game.rom';self.rom.write_bytes(b'rom')
        self.system = dict(id='test', core=str(self.core), system_dir=str(self.install/'system'))

    def test_path_resolution_including_custom_core_and_explicit_override(self):
        cfg = {'system_dir':str(self.install/'system')}
        self.assertEqual(ra.validate_pick(self.system,self.rom,{},self.root)['exe'],self.exe)
        local = self.root/'cores/x1.dll';local.parent.mkdir();local.touch()
        system = dict(id='x1',core='cores/x1.dll')
        self.assertEqual(ra.validate_pick(system,self.rom,cfg,self.root)['core'],local)
        other = self.root/'another.exe';other.touch()
        self.assertEqual(ra.validate_pick(system,self.rom,dict(cfg,retroarch_path='another.exe'),self.root)['exe'],other)
        with self.assertRaises(FileNotFoundError):ra.validate_pick(system,self.rom,dict(cfg,retroarch_path='missing.exe'),self.root)
        with self.assertRaises(ValueError):ra.validate_pick(system,self.rom,dict(cfg,retroarch_path=123),self.root)
        with self.assertRaises(FileNotFoundError):ra.validate_pick(self.system,self.root/'missing',{},self.root)

    def test_real_shared_channel_roundtrip_reset_owner_and_unavailable(self):
        channel=ra.LaunchChannel();self.addCleanup(channel.close)
        env={};channel.apply(env);self.assertIsNone(channel.read(os.getpid()))
        with patch.dict(os.environ,env):ra.request_launch(self.system,self.rom,{},self.root)
        value=channel.read(os.getpid());self.assertEqual(value['rom'],str(self.rom))
        self.assertEqual(value['system'],self.system)
        with self.assertRaises(ValueError):channel.read(os.getpid()+1)
        channel.apply(env);self.assertIsNone(channel.read(os.getpid()))
        channel.mapping[:8]=ra.HEADER.pack(b'RNSL',ra.SIZE)
        with self.assertRaises(ValueError):channel.read(os.getpid())
        with patch.dict(os.environ,{ra.ENV_KEY:''}):
            with self.assertRaises(RuntimeError):ra.request_launch(self.system,self.rom,{},self.root)

    def test_normal_content_uses_original_and_does_not_create_cache(self):
        pick=ra.validate_pick(self.system,self.rom,{},self.root)
        self.assertEqual(ra.prepare_content(pick,self.root),(self.rom,self.install/'system',None))
        self.assertFalse((self.root/'state').exists())

    def test_archive_selection_matches_saver_and_cached_data_is_preserved(self):
        archive=self.root/'game.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('a.rom',b'1');z.writestr('日本語/b.rom',b'12345');z.writestr('readme.txt',b'longer text')
        system=dict(self.system,archive_mode='extract',content_extensions=['.rom'])
        pick=ra.validate_pick(system,archive,{},self.root)
        content,_,folder=ra.prepare_content(pick,self.root)
        self.assertEqual(content.name,'b.rom');self.assertEqual(content.read_bytes(),b'12345')
        content.write_bytes(b'kept edits')
        self.assertEqual(ra.prepare_content(pick,self.root)[0].read_bytes(),b'kept edits')
        manifest=json.loads((folder/'content.json').read_text(encoding='utf-8'))
        manifest['content']=str(self.rom);(folder/'content.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):ra.prepare_content(pick,self.root)

    def test_all_computer_disk_pairs_persist_with_distinct_game_names(self):
        for sid,ext in (('pc88','.d88'),('pc98','.hdm'),('x1','.d88'),('x68000','.dim'),('fm7','.d77')):
            with self.subTest(sid=sid):
                roms=self.root/sid;roms.mkdir()
                first=roms/'Game (Disk A)';first=first.with_suffix(ext);first.write_bytes(b'one')
                second=roms/'Game (Disk B)';second=second.with_suffix(ext);second.write_bytes(b'two')
                bios=self.install/'system'
                sub={'pc98':'np2kai','x1':'xmil','x68000':'keropi'}.get(sid)
                if sub:(bios/sub).mkdir(parents=True,exist_ok=True);(bios/sub/'bios.rom').write_bytes(b'bios')
                if sid=='fm7':(roms/'fm7.zip').write_bytes(b'bios')
                system=dict(self.system,id=sid,rom_dir=str(roms),disk_boot_mode='pc88_two_drives' if sid=='pc88' else 'computer_two_drives')
                pick=ra.validate_pick(system,first,{},self.root)
                content,directory,folder=ra.prepare_content(pick,self.root)
                self.assertTrue(content.name.startswith('Game (Disk A)_'))
                files=list(folder.glob('*'+ext));self.assertEqual(sorted(p.read_bytes() for p in files),[b'one',b'two'])
                files[0].write_bytes(b'game progress')
                again=ra.prepare_content(pick,self.root)
                self.assertEqual(again,(content,directory,folder));self.assertEqual(files[0].read_bytes(),b'game progress')
                self.assertEqual(first.read_bytes(),b'one');self.assertEqual(second.read_bytes(),b'two')
                text=content.read_text(encoding='utf-8')
                if sid=='fm7':self.assertIn('-flop1',text);self.assertIn('-flop2',text)
                elif sid=='pc98':self.assertTrue(text.startswith('np2kai '))
                else:self.assertEqual(len(text.splitlines()),2)

    def test_failed_new_preparation_is_cleaned_but_existing_files_not_removed(self):
        bad=self.root/'bad.zip';bad.write_bytes(b'not zip')
        pick=ra.validate_pick(dict(self.system,archive_mode='extract'),bad,{},self.root)
        with self.assertRaises(zipfile.BadZipFile):ra.prepare_content(pick,self.root)
        self.assertFalse(list((self.root/'state/retroarch_content').iterdir()))

    def test_launch_uses_arg_list_normal_core_and_leaves_user_config_untouched(self):
        config=self.install/'retroarch.cfg';config.write_bytes(b'user settings')
        value=dict(system=dict(self.system,_favorite_startup_input={'key':'Start'}),rom=str(self.rom))
        with patch('desktop_launch.start_process',return_value=123) as start,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ra.launch(value,{},self.root),123)
        cmd,cwd=start.call_args.args
        self.assertEqual(cmd[:3],[str(self.exe),'-L',str(self.core)])
        self.assertEqual(cmd[-1],str(self.rom));self.assertEqual(cwd,self.install)
        text=Path(cmd[4]).read_text(encoding='utf-8')
        self.assertIn('config_save_on_exit = "false"',text)
        self.assertNotIn('savefile_directory',text);self.assertNotIn('input_',text)
        self.assertEqual(config.read_bytes(),b'user settings')
        with patch('desktop_launch.start_process',side_effect=OSError('denied')):
            with self.assertRaises(OSError):ra.launch(value,{},self.root)
        self.assertEqual(len(list((self.root/'state/retroarch_launch').glob('*.cfg'))),1)

    def test_configuration_rejects_embedded_lines(self):
        for value in ('bad\npath','bad"path','bad\rpath','bad\x00path'):
            with self.assertRaises(ValueError):ra.config_value(value)


class EnterTests(unittest.TestCase):
    def record(self):
        return dict(proc=Mock(poll=Mock(return_value=None)),ready=True,pick=({'id':'x'},Path('game.rom')))

    def test_hidden_enter_exits_selected_enter_is_once_and_expires(self):
        clock=[0.];control=ui.Selection([self.record()],lambda:clock[0])
        self.assertFalse(ui.handle_message(control,0x100,ui.ENTER,0))
        control.key(ui.RIGHT)
        self.assertTrue(ui.handle_message(control,0x100,ui.ENTER,0))
        self.assertTrue(ui.handle_message(control,0x100,ui.ENTER,1<<30))
        self.assertEqual(len(control.actions),1)
        clock[0]=6
        self.assertFalse(ui.handle_message(control,0x100,ui.ENTER,0))
        self.assertFalse(ui.handle_message(ui.ForwardKeys(Mock(),lambda:None),0x100,ui.ENTER,0))

    def run_action(self,control,callback,dispose):
        control.publish=Mock()
        ui.process_actions(control,control.slots,{}, {},Path('unused'),Path('unused'),{}, {},
                           Mock(),set(),dispose,[0.],0.,launch_request=callback)

    def test_exact_record_launch_keeps_lists_and_defers_disposal_to_scheduler(self):
        record=self.record();control=ui.Selection([record]);control.key(ui.RIGHT);control.key(ui.ENTER)
        callback=Mock();dispose=Mock();self.run_action(control,callback,dispose)
        callback.assert_called_once_with(*record['pick']);dispose.assert_not_called()
        self.assertFalse(control.actions)
        control.key(ui.ENTER);control.slots[0]=self.record();callback.reset_mock()
        self.run_action(control,callback,dispose);callback.assert_not_called()

    def test_failed_request_keeps_tile_and_reports_distinct_error(self):
        control=ui.Selection([self.record()]);control.key(ui.RIGHT);control.key(ui.ENTER)
        dispose=Mock()
        with contextlib.redirect_stdout(io.StringIO()):self.run_action(control,Mock(side_effect=FileNotFoundError('RetroArch missing')),dispose)
        dispose.assert_not_called();self.assertEqual(control.status,ui.LAUNCH_ERROR)



if __name__=='__main__':unittest.main()
