"""PostgreSQL adapter for the existing parameterized repository queries.

No connection string is written to disk or included in an exception. SQLite
remains the zero-dependency local backend; this module is loaded only for PG.
"""
import re
import sqlite3

WRITE_LOCK = 726377040221


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names=[column.name for column in cursor.description or []]
    return lambda values: Row(zip(names,values))


def parameters_sql(statement):
    """Convert qmark parameters, leaving quoted SQL question marks intact."""
    result=[];quote=None;index=0
    while index<len(statement):
        char=statement[index]
        if char=='%':
            result.append('%%')
        elif quote:
            result.append(char)
            if char==quote:
                if index+1<len(statement) and statement[index+1]==quote:
                    result.append(statement[index+1]);index+=1
                else:quote=None
        elif char in ("'",'"'):
            quote=char;result.append(char)
        else:
            result.append('%s' if char=='?' else char)
        index+=1
    return ''.join(result)


class PostgresConnection:
    def __init__(self, dsn):
        try:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict,make_conninfo
        except ImportError:
            raise RuntimeError('Instale requirements.txt para conectar ao PostgreSQL.') from None
        self._driver=psycopg
        try:
            options=conninfo_to_dict(dsn)
            host=options.get('host','')
            if host not in ('localhost','127.0.0.1','::1'):
                if options.get('sslmode') not in ('require','verify-ca','verify-full'):
                    options['sslmode']='require'
            options.setdefault('connect_timeout','15')
            self._connection=psycopg.connect(make_conninfo(**options),autocommit=True,row_factory=row_factory,prepare_threshold=None)
        except Exception:
            raise RuntimeError('Não foi possível conectar ao PostgreSQL. Confira DATABASE_URL e o acesso ao banco.') from None
        self._track_cache={};self._person_cache={}

    def execute(self, statement, parameters=None):
        try:
            if parameters is None:
                return self._connection.execute(statement)
            return self._connection.execute(parameters_sql(statement),parameters)
        except self._driver.IntegrityError:
            raise sqlite3.IntegrityError('Conflito de integridade no banco.') from None
        except self._driver.Error as error:
            raise RuntimeError(f'Falha de consulta PostgreSQL (SQLSTATE {error.sqlstate or "unknown"}).') from None

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.rollback() if kind else self.commit()
        finally:
            self.close()


SEARCH_FUNCTION = r"""
CREATE OR REPLACE FUNCTION search_key(value TEXT) RETURNS TEXT
LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS $ressoa$
 SELECT regexp_replace(lower(normalize(coalesce(value,''),NFKD)),U&'[\0300-\036f]','','g')
$ressoa$
"""


def initialize(dsn, sqlite_schema):
    schema=sqlite_schema.replace(' COLLATE NOCASE','').replace('expires_at REAL','expires_at DOUBLE PRECISION').replace('reset_at REAL','reset_at DOUBLE PRECISION')
    schema=re.sub(r'PRAGMA\s+user_version\s*=\s*\d+\s*;','',schema)
    with PostgresConnection(dsn) as db:
        db.execute('BEGIN')
        db.execute('SELECT pg_advisory_xact_lock(?)',(WRITE_LOCK,))
        for statement in schema.split(';'):
            if statement.strip():db.execute(statement)
        db.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_private INTEGER NOT NULL DEFAULT 0')
        db.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS lyric_excerpt TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS feed_published_at TEXT NOT NULL DEFAULT ''")
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_email_ci ON users(lower(email))')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_username_ci ON users(lower(username))')
        db.execute(SEARCH_FUNCTION)
        db.execute('CREATE TABLE IF NOT EXISTS ressoa_schema (version INTEGER PRIMARY KEY)')
        db.execute('INSERT INTO ressoa_schema VALUES (1) ON CONFLICT DO NOTHING')
        db.execute('INSERT INTO ressoa_schema VALUES (2) ON CONFLICT DO NOTHING')
        db.execute('INSERT INTO ressoa_schema VALUES (3) ON CONFLICT DO NOTHING')
        db.execute('INSERT INTO ressoa_schema VALUES (4) ON CONFLICT DO NOTHING')
