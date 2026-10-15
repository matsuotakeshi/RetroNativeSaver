from datetime import datetime, timezone
import unittest
from tools.summarize_startup import summarize


def process(pid,created,parent=None,rows=None):
    return dict(file=f'{pid}-{created}.jsonl',pid=pid,created=created,parent=parent or {},rows=rows or [])


def point(name,clock,**data):
    return dict(event='startup_point',name=name,monotonic=clock,**data)


class StartupSummaryTests(unittest.TestCase):
    def fixture(self):
        ft=133801632000000000  # Exact 2025-01-01 UTC for a deterministic origin.
        root=process(1,ft,rows=[dict(event='process_entry',time='2025-01-01T00:00:00.100+00:00',monotonic=100.)])
        worker=process(2,ft+100,dict(pid=1,creation_filetime=ft),[
            point('layout',101.,slots=2,independent=True),
            point('tile_spawn_begin',102.),point('tile_spawned',102.1,target_pid=3,slot=1),
            point('tile_spawn_begin',104.),point('tile_spawned',104.1,target_pid=4,slot=2)])
        children=[]
        for pid,slot,clock in [(3,1,103.),(4,2,105.)]:
            children.append(process(pid,ft+pid,dict(pid=2,creation_filetime=ft+100),[
                dict(event='process_entry',monotonic=clock-.5),
                point('first_frame_ready',clock,slot=slot),
                point('first_game_gdi_submit',clock+.1,slot=slot),
                point('first_unfaded_gdi_submit',clock+.8,slot=slot)]))
        return [root,worker,*children]

    def test_first_frame_submit_and_all_initial_are_distinct(self):
        result=summarize(self.fixture())[0]
        self.assertEqual(result['metrics']['first_frame_ready']['first'],3.1)
        self.assertEqual(result['metrics']['first_game_gdi_submit']['all_initial'],5.2)
        self.assertEqual(result['metrics']['first_unfaded_gdi_submit']['all_initial'],5.9)
        self.assertFalse(result['physical_visibility_verified'])

    def test_missing_tile_never_reports_all_complete(self):
        rows=self.fixture();rows.pop()
        result=summarize(rows)[0]
        self.assertEqual(result['missing_slots'],[2])
        self.assertIsNone(result['metrics']['first_game_gdi_submit']['all_initial'])

    def test_pid_reuse_with_different_parent_identity_is_ignored(self):
        rows=self.fixture()
        reused=process(3,999,dict(pid=2,creation_filetime=777),[
            dict(event='process_entry',monotonic=102.6),point('first_game_gdi_submit',102.7,slot=1)])
        result=summarize(rows+[reused])[0]
        self.assertEqual(result['metrics']['first_game_gdi_submit']['first'],3.2)

    def test_failed_first_generation_is_not_completed_by_replacement(self):
        rows=self.fixture(); rows[2]['rows']=rows[2]['rows'][:1]
        rows[1]['rows'] += [point('tile_spawn_begin',110.),point('tile_spawned',110.1,target_pid=3,slot=1)]
        rows.append(process(3,999,rows[2]['parent'],[
            dict(event='process_entry',monotonic=110.5),point('first_game_gdi_submit',111.,slot=1)]))
        result=summarize(rows)[0]
        self.assertIsNone(result['metrics']['first_game_gdi_submit']['all_initial'])


if __name__=='__main__':unittest.main()
