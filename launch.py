"""Portable launcher: no installer, internet, Node, or pip required."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
# Embedded Python isolates sys.path by default; explicitly trust our own folder.
sys.path.insert(0, str(ROOT))
import argparse
import hashlib
import json
import logging
import os
import socket
import threading
import webbrowser

def self_check():
    import sqlite3
    import backend
    assert hasattr(hashlib, 'scrypt'), 'Runtime tidak mendukung scrypt'
    backend.hashpw('self-check-only', '00' * 16)
    assert backend.now().endswith('+08:00')
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE check_db(id INTEGER)')
    for name in ('index.html','app.js','styles.css','backend.py'):
        if not (ROOT/name).is_file(): raise RuntimeError('Berkas paket tidak lengkap: '+name)
    return backend

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--mode',choices=('local','lan'))
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--port',type=int,default=4173)
    args=parser.parse_args()
    backend=self_check()
    if args.check:
        print('OK: Python, scrypt, SQLite, timezone UTC+8, dan aset aplikasi.'); return
    os.chdir(ROOT)
    backend.DB.parent.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=backend.DB.parent/'launcher.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    backend.initialize()
    print('\nNILLA DAILY MART 0.3.0\n')
    mode=args.mode
    if not mode:
        print('1. Mulai di komputer ini (bisa tanpa internet)')
        print('2. Buka untuk perangkat di Wi-Fi/LAN toko')
        print('3. Keluar')
        choice=input('\nPilih 1, 2, atau 3 lalu Enter [1]: ').strip() or '1'
        if choice=='3': return
        if choice not in ('1','2'): raise RuntimeError('Pilihan tidak dikenal. Jalankan lagi dan pilih 1 atau 2.')
        mode='lan' if choice=='2' else 'local'
    if mode=='lan':
        with backend.connect() as db:
            if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                print('\nBuat akun owner di mode 1 terlebih dahulu. Mode jaringan belum dibuka.'); return
        print('\nMode LAN: perangkat harus berada di jaringan toko yang dipercaya.')
        print('Koneksi LAN ini memakai HTTP. Untuk akses melalui internet gunakan hosting HTTPS.')
        print('Jika Windows Firewall bertanya, izinkan hanya jaringan Private.')
    host='0.0.0.0' if mode=='lan' else '127.0.0.1'
    try:
        server=backend.ThreadingHTTPServer((host,args.port),backend.Handler)
    except OSError as error:
        raise RuntimeError(f'Port {args.port} sedang dipakai atau tidak tersedia. Tutup jendela Nilla lain lalu coba lagi. Detail: {error}') from error
    url=f'http://127.0.0.1:{server.server_port}'
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        # Check actual application response before opening the browser.
        import urllib.request
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url+'/api/status',timeout=5) as response:
            status=json.load(response)
        if status.get('application')!='nilla-daily-mart': raise RuntimeError('Server tidak lolos pemeriksaan kesiapan.')
        print('\nAPLIKASI SIAP: '+url)
        print('Data toko: '+str(backend.DB.resolve()))
        if mode=='lan':
            addresses=sorted({a[4][0] for a in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET) if not a[4][0].startswith('127.')})
            for ip in addresses: print('Alamat perangkat lain: http://'+ip+':'+str(server.server_port))
            if not addresses: print('Lihat alamat IPv4 komputer di Pengaturan Jaringan Windows.')
        if not args.no_browser: webbrowser.open(url)
        print('\nJangan tutup jendela ini saat kasir bekerja.')
        print('B = buka browser lagi | Q = hentikan server dan keluar')
        while True:
            choice=input('Pilihan: ').strip().lower()
            if choice=='q': break
            if choice=='b': webbrowser.open(url)
    except (KeyboardInterrupt,EOFError): pass
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        print('Server berhenti. Data tetap tersimpan.')

if __name__=='__main__':
    try: main()
    except Exception as error:
        logging.exception('Launcher failed')
        print('\nGAGAL MEMULAI: '+str(error))
        print('Salin pesan di atas untuk bantuan. Database tidak dihapus.')
        sys.exit(1)
