"""Consistent SQLite backup, including writes still in the WAL."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or not source.is_file() or destination.exists():
        raise ValueError('A origem precisa existir; o destino deve ser um arquivo novo e diferente.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(destination)) as copy:
            with copy:
                original.backup(copy)
            if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Falha na verificação do backup.')
    return destination


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description='Backup consistente do banco Ressoa')
    parser.add_argument('--source', default=os.getenv('DATABASE_PATH', str(root / 'storage' / 'ressoa.sqlite3')))
    parser.add_argument('--output', default=str(root / 'storage' / 'backups' / ('ressoa-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')))
    args = parser.parse_args()
    print(backup(args.source, args.output))
