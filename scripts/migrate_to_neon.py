"""Copy SQLite into an EMPTY PostgreSQL database. Default is a dry-run check.
DATABASE_URL is read from the environment, never from command-line arguments.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import json
import os
import sqlite3
from contextlib import closing
from database import Database

TABLES=('tracks','users','posts','weekly','follows','follow_requests','actions','shares')


def migrate(source_path,target,apply=False):
    source_path=Path(source_path).resolve()
    if not source_path.is_file():raise ValueError('Banco SQLite de origem não encontrado.')
    if not target.is_postgres:raise ValueError('O destino precisa ser PostgreSQL.')
    with closing(sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)) as original:
        with closing(sqlite3.connect(':memory:')) as source:
            original.backup(source)
            if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or source.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Verifique a integridade do banco de origem antes de migrar.')
            available={row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not (set(TABLES)-{'shares'})<=available:raise ValueError('A origem não tem o schema de contas atual do Ressoa.')
            counts={table:source.execute(f'SELECT count(*) FROM {table}').fetchone()[0] if table in available else 0 for table in TABLES}
            with target.transaction() as destination:
                existing={table:destination.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in TABLES}
                empty=not any(existing.values())
                if not apply:return dict(mode='check',source_counts=counts,target_empty=empty,can_apply=empty)
                if not empty:raise ValueError('O destino já tem dados. Migração cancelada para não sobrescrever contas ou diários.')
                for table in TABLES:
                    if table not in available:continue
                    cursor=source.execute(f'SELECT * FROM {table}')
                    columns=[column[0] for column in cursor.description]
                    permitted={row['column_name'] for row in destination.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?',(table,)).fetchall()}
                    if set(columns)!=permitted:raise ValueError('Schemas incompatíveis. Nenhum dado foi copiado.')
                    names=','.join('"'+name.replace('"','""')+'"' for name in columns)
                    marks=','.join('?' for _ in columns)
                    for row in cursor:destination.execute(f'INSERT INTO {table} ({names}) VALUES ({marks})',row)
                for table,count in counts.items():
                    if destination.execute(f'SELECT count(*) FROM {table}').fetchone()[0]!=count:
                        raise ValueError('Verificação falhou; transação cancelada.')
            return dict(mode='applied',copied_counts=counts,source_unchanged=True,sessions_copied=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Verificar/copiar SQLite do Ressoa para um Neon vazio')
    parser.add_argument('--source',default=str(Path(__file__).resolve().parents[1]/'storage'/'ressoa.sqlite3'))
    parser.add_argument('--apply',action='store_true',help='Copiar somente se o destino estiver vazio')
    args=parser.parse_args()
    url=os.getenv('DATABASE_URL','')
    if not url.startswith(('postgresql://','postgres://')):parser.error('Defina DATABASE_URL com a conexão privada do Neon no ambiente.')
    try:
        print(json.dumps(migrate(args.source,Database(url),args.apply),ensure_ascii=False))
    except (ValueError,RuntimeError,sqlite3.Error):
        raise SystemExit('Migração não concluída. Confira conexão, integridade da origem e destino vazio; o SQLite original foi preservado.') from None
