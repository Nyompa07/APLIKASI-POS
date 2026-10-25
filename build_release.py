"""Build a flat, offline Windows package; never include prior ZIPs or store data."""
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'build/python-3.13.9-embed-amd64.zip'
OUTPUT=ROOT/'Nilla-Daily-Mart-v0.3.0-Portable-Windows-x64.zip'
PREFIX='Nilla-Daily-Mart-v0.3.0/'
FILES=['MULAI-NILLA.bat','Jalankan-Nilla-Daily-Mart.bat','BACA-DULU.txt','launch.py','backend.py','index.html','app.js','styles.css','server.js','package.json','backup.py','README.md','DESIGN.md','MASTER_PROMPT.md','MASTER_PROMPT_USER.txt','VALIDATION.md','test_backend.py','test_launcher.py']

def build():
    digest=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    expected=(ROOT/'runtime.sha256').read_text().split()[0]
    if digest!=expected: raise RuntimeError('Runtime checksum differs from verified download')
    with zipfile.ZipFile(SOURCE) as runtime, zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED) as out:
        if runtime.testzip(): raise RuntimeError('Corrupt runtime')
        for name in FILES:
            data=(ROOT/name).read_bytes()
            if name.endswith('.bat') or name=='BACA-DULU.txt': data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            out.writestr(PREFIX+name,data)
        for item in runtime.infolist():
            if '/' in item.filename or '\\' in item.filename or item.filename in ('.','..'): raise RuntimeError('Unexpected runtime entry')
            out.writestr(PREFIX+'runtime/'+item.filename,runtime.read(item))
        out.writestr(PREFIX+'RUNTIME-SOURCE.txt','CPython 3.13.9 Windows embedded x64\nSource: https://www.python.org/ftp/python/3.13.9/python-3.13.9-embed-amd64.zip\nSHA256: '+digest+'\nLicense: runtime/LICENSE.txt\nDownloaded via verified HTTPS. No Python installation required.\n')
    with zipfile.ZipFile(OUTPUT) as archive:
        assert archive.testzip() is None
        assert not any(n.endswith('.zip') and '/runtime/' not in n for n in archive.namelist())
        assert not any('/data/' in n for n in archive.namelist())
    print(OUTPUT.name,OUTPUT.stat().st_size,'bytes',hashlib.sha256(OUTPUT.read_bytes()).hexdigest())

if __name__=='__main__': build()
