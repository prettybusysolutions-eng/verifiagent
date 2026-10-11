"""Actual Docker enforcement; missing Docker/image is an error, never a skip."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from services.isolated_runner import IsolatedRunner

class DockerRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image=os.environ['WORKER_IMAGE']
        subprocess.run(['docker','info'],check=True,capture_output=True)
        subprocess.run(['docker','image','inspect',cls.image],check=True,capture_output=True)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.source=Path(self.temp.name)
        self.source.chmod(0o755)
        (self.source/'original.txt').write_text('unchanged')

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_process_and_filesystem_network_boundaries(self):
        code='''import os,socket,json
from pathlib import Path
checks={'nonroot':os.geteuid()!=0,'source_readable':Path('/source/original.txt').read_text()=='unchanged'}
Path('/work/result.txt').write_text('actual-side-effect')
checks['work_writable']=Path('/work/result.txt').read_text()=='actual-side-effect'
for name,path in [('root_readonly','/forbidden'),('source_readonly','/source/forbidden')]:
 try:Path(path).write_text('bad');checks[name]=False
 except OSError:checks[name]=True
try:
 socket.create_connection(('1.1.1.1',53),timeout=2).close();checks['network_disabled']=False
except OSError:checks['network_disabled']=True
status=Path('/proc/self/status').read_text()
checks['no_new_privileges']='NoNewPrivs:\\t1' in status
checks['no_capabilities']='CapEff:\\t0000000000000000' in status
print(json.dumps(checks))
raise SystemExit(0 if all(checks.values()) else 9)
'''
        result=IsolatedRunner(self.image)('python -c '+shlex.quote(code),self.source)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertTrue(all(json.loads(result.stdout).values()))
        self.assertEqual((self.source/'original.txt').read_text(),'unchanged')
        self.assertFalse((self.source/'result.txt').exists())
        self.assertFalse((self.source/'forbidden').exists())

    def test_nonzero_exit_is_preserved(self):
        result=IsolatedRunner(self.image)('python -c "raise SystemExit(17)"',self.source)
        self.assertEqual(result.returncode,17)

    def test_timeout_removes_actual_container(self):
        before=subprocess.check_output(['docker','ps','-aq','--filter','name=verifiagent-'],text=True).split()
        with self.assertRaises(subprocess.TimeoutExpired):
            IsolatedRunner(self.image,timeout_seconds=2)('sleep 60',self.source)
        after=subprocess.check_output(['docker','ps','-aq','--filter','name=verifiagent-'],text=True).split()
        self.assertEqual(set(after),set(before))

if __name__=='__main__':unittest.main(verbosity=2)
