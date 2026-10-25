"""Tests run using bundled Windows Python as well as Linux Python."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
import launch

class LauncherTests(unittest.TestCase):
    def test_preflight(self): launch.self_check()
    def test_timezone_without_iana_database(self):
        import zoneinfo
        old=zoneinfo.TZPATH
        try:
            zoneinfo.reset_tzpath([]);zoneinfo.ZoneInfo.clear_cache()
            import importlib, backend
            importlib.reload(backend)
            self.assertTrue(backend.now().endswith('+08:00'))
        finally: zoneinfo.reset_tzpath(old)
    def test_start_health_stop_and_port_conflict(self):
        with tempfile.TemporaryDirectory(prefix='nilla path spaces ') as temp:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            env=dict(os.environ,NILLA_DB=str(Path(temp)/'data.sqlite3'))
            command=[sys.executable,str(launch.ROOT/'launch.py'),'--mode','local','--no-browser','--port',str(port)]
            process=subprocess.Popen(command,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));status=None
                for _ in range(100):
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/api/status',timeout=.5) as r: status=json.load(r)
                        break
                    except OSError:
                        if process.poll() is not None: break
                        time.sleep(.1)
                self.assertIsNotNone(status);self.assertEqual(status['application'],'nilla-daily-mart')
                duplicate=subprocess.run(command,env=env,input='',capture_output=True,text=True,timeout=10)
                self.assertNotEqual(duplicate.returncode,0);self.assertIn('Port',duplicate.stdout)
            finally:
                output,_=process.communicate('q\n',timeout=10)
            self.assertEqual(process.returncode,0,output);self.assertIn('Server berhenti',output)
            self.assertTrue(Path(env['NILLA_DB']).is_file())
    def test_lan_requires_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([sys.executable,str(launch.ROOT/'launch.py'),'--mode','lan','--no-browser'],env=dict(os.environ,NILLA_DB=str(Path(temp)/'new.sqlite3')),input='',capture_output=True,text=True,timeout=10)
            self.assertIn('Buat akun owner',result.stdout)

if __name__=='__main__':
    import test_backend
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(LauncherTests),unittest.defaultTestLoader.loadTestsFromModule(test_backend)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
