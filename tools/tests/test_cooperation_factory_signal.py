"""The real CLI must unwind its existing owner cleanup after SIGTERM."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class FactorySignalTests(unittest.TestCase):
    def test_sigterm_unwinds_original_run_instead_of_abandoning_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            script=root/'coordinator.py'
            script.write_text('''import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import cooperation_factory as factory
root=Path(sys.argv[2])
factory.read_json=lambda path: {}
factory.reference=lambda *args,**kwargs: {}
def original_run(*args):
    try:
        (root/'ready').write_text('original owner running')
        time.sleep(30)
    finally:
        (root/'cleaned').write_text('original run cleanup reached')
factory.run=original_run
raise SystemExit(factory.main(['run','--manifest',str(root/'manifest'),
                              '--output',str(root/'output')]))
''')
            tools=Path(__file__).resolve().parents[1]
            child=subprocess.Popen([sys.executable,'-B',str(script),str(tools),str(root)],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+5
                while not (root/'ready').exists() and child.poll() is None and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertTrue((root/'ready').exists())
                os.kill(child.pid,signal.SIGTERM)
                output,error=child.communicate(timeout=5)
                self.assertEqual(child.returncode,2,(output,error))
                self.assertEqual((root/'cleaned').read_text(),'original run cleanup reached')
                self.assertIn('SIGTERM',output)
                self.assertIn('unknown',output)
            finally:
                if child.poll() is None:
                    child.kill();child.communicate(timeout=5)


if __name__=='__main__':unittest.main()
