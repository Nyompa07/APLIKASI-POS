"""Snapshot or restore SQLite without overwriting an existing file."""
import os
from pathlib import Path
import sqlite3
import sys

if len(sys.argv)!=3: raise SystemExit('Usage: python3 backup.py SOURCE.sqlite3 NEW_DESTINATION.sqlite3')
source,target=map(Path,sys.argv[1:])
if not source.is_file(): raise SystemExit('Source database not found')
target.parent.mkdir(parents=True,exist_ok=True)
fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
src=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)
dst=sqlite3.connect(target)
try:
    src.backup(dst)
    if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise SystemExit('Backup integrity check failed')
    if dst.execute('PRAGMA foreign_key_check').fetchall(): raise SystemExit('Backup relationship check failed')
    dst.execute('DELETE FROM sessions'); dst.execute('DELETE FROM attempts'); dst.commit()
finally:
    dst.close()
    src.close()
print('SQLite snapshot verified; sessions cleared. Destination:',target)
