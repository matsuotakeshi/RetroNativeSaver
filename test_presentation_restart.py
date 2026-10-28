"""Real temporary-file handoff; no ROMs, installed settings or native cores."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import presentation_restart as restart


class PresentationRestartTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.state=({('msx','日本語/game.dsk'),('gb','a.gb')},{'MSX'},{'MSX':3})

    def test_worker_request_then_parent_seed_preserves_exact_failure_state(self):
        self.assertEqual(restart.read_state(self.root,0),(set(),set(),{}))
        restart.write_state(self.root,*self.state,pid=123)
        actual=restart.read_state(self.root,123);self.assertEqual(actual,self.state)
        restart.write_state(self.root,*actual,pid=0)
        self.assertEqual(restart.read_state(self.root,0),self.state)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),[restart.FILENAME])

    def test_missing_wrong_or_malformed_request_never_defaults_to_empty(self):
        with self.assertRaises(FileNotFoundError):restart.read_state(self.root,123)
        restart.write_state(self.root,*self.state,pid=123)
        with self.assertRaises(ValueError):restart.read_state(self.root,124)
        good=json.loads((self.root/restart.FILENAME).read_bytes())
        for changes in ({'pid':True},{'banned':['bad']},{'banned':[[1,2]]},
                        {'suspended':None},{'failures':{'x':-1}},{'failures':{'x':True}}):
            (self.root/restart.FILENAME).write_text(json.dumps(dict(good,**changes)))
            with self.assertRaises(ValueError):restart.read_state(self.root,123)

    def test_oversize_or_failed_replace_keeps_existing_state(self):
        restart.write_state(self.root,*self.state,pid=0)
        with patch.object(restart,'MAX_BYTES',2):
            with self.assertRaises(ValueError):restart.read_state(self.root,0)
            with self.assertRaises(ValueError):restart.write_state(self.root,*self.state,pid=123)
        with patch.object(restart.os,'replace',side_effect=OSError('denied')):
            with self.assertRaises(OSError):restart.write_state(self.root,*self.state,pid=123)
        self.assertEqual(restart.read_state(self.root,0),self.state)


if __name__=='__main__':unittest.main()
