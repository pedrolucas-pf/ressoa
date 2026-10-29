"""PostgreSQL adapter for the existing parameterized repository queries.

No connection string is written to disk or included in an exception. SQLite
remains the local backend; this module is loaded only for PG.
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


def connection_info(dsn):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    options = conninfo_to_dict(dsn)
    if options.get('host', '') not in ('localhost', '127.0.0.1', '::1'):
        if options.get('sslmode') not in ('require', 'verify-ca', 'verify-full'):
            options['sslmode'] = 'require'
    options.setdefault('connect_timeout', '15')
    return make_conninfo(**options)


def create_pool(dsn):
    import atexit
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(connection_info(dsn), name='ressoa', min_size=0, max_size=8,
        max_idle=60, max_lifetime=600, timeout=15, num_workers=2, open=True,
        kwargs=dict(autocommit=True, row_factory=row_factory, prepare_threshold=None),
        check=ConnectionPool.check_connection)
    atexit.register(pool.close)
    return pool


class PostgresConnection:
    def __init__(self, dsn, pool=None):
        try:
            import psycopg
        except ImportError:
            raise RuntimeError('Instale requirements.txt para conectar ao PostgreSQL.') from None
        self._driver=psycopg
        self._pool=pool
        self._released=False
        try:
            self._connection=pool.getconn() if pool is not None else psycopg.connect(connection_info(dsn),autocommit=True,row_factory=row_factory,prepare_threshold=None)
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

    def fetch_many(self, queries):
        try:
            with self._connection.pipeline():
                cursors = [self.execute(statement, parameters) for statement, parameters in queries]
            return [cursor.fetchall() for cursor in cursors]
        except self._driver.Error as error:
            raise RuntimeError(f'Falha de consulta PostgreSQL (SQLSTATE {error.sqlstate or "unknown"}).') from None

    def rollback(self):
        self._connection.rollback()

    def close(self):
        if self._released:
            return
        self._released=True
        if self._pool is None:
            self._connection.close()
        else:
            self._pool.putconn(self._connection)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.rollback() if kind else self.commit()
        finally:
            self.close()


class ConnectionLease:
    """Independent query caches over the connection owned by one HTTP request."""
    def __init__(self, connection):
        self._connection = connection
        self._track_cache = {}
        self._person_cache = {}

    def execute(self, statement, parameters=None):
        return self._connection.execute(statement, parameters)

    def fetch_many(self, queries):
        return self._connection.fetch_many(queries)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        # The request scope closes the underlying connection after all operations.
        pass

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.rollback() if kind else self.commit()


SEARCH_FUNCTION = r"""
CREATE OR REPLACE FUNCTION search_key(value TEXT) RETURNS TEXT
LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS $ressoa$
 SELECT regexp_replace(normalize(username_key(coalesce(value,'')),NFKD),U&'[\0300-\036f]','','g')
$ressoa$
"""


def initialize(dsn, sqlite_schema):
    schema=sqlite_schema.replace(' COLLATE NOCASE','').replace(' COLLATE BINARY',' COLLATE "C"').replace('expires_at REAL','expires_at DOUBLE PRECISION').replace('reset_at REAL','reset_at DOUBLE PRECISION')
    schema=re.sub(r'PRAGMA\s+user_version\s*=\s*\d+\s*;','',schema)
    with PostgresConnection(dsn) as db:
        db.execute('BEGIN')
        db.execute('SELECT pg_advisory_xact_lock(?)',(WRITE_LOCK,))
        # Compare Unicode names independently of the database's default locale.
        collation = db.execute("SELECT collname FROM pg_collation WHERE collname IN ('und-x-icu','pg_c_utf8') ORDER BY CASE WHEN collname='und-x-icu' THEN 0 ELSE 1 END LIMIT 1").fetchone()
        if not collation:
            raise RuntimeError('O PostgreSQL precisa de uma collation Unicode para os nomes de usuário.')
        db.execute(f'''CREATE OR REPLACE FUNCTION username_key(value TEXT) RETURNS TEXT
            LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS $ressoa$
            SELECT lower(normalize(value,NFC) COLLATE "{collation['collname']}")
            $ressoa$''')
        for statement in schema.split(';'):
            if statement.strip():db.execute(statement)
        db.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_private INTEGER NOT NULL DEFAULT 0')
        db.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS lyric_excerpt TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS feed_published_at TEXT NOT NULL DEFAULT ''")
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_email_ci ON users(lower(email))')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_username_exact ON users(username COLLATE "C")')
        db.execute('DROP INDEX IF EXISTS users_username_ci')
        db.execute('DROP INDEX IF EXISTS users_username_unicode_ci')
        db.execute('CREATE INDEX IF NOT EXISTS users_email_unicode ON users(username_key(email))')
        db.execute(SEARCH_FUNCTION)
        db.execute('CREATE TABLE IF NOT EXISTS ressoa_schema (version INTEGER PRIMARY KEY)')
        db.execute('INSERT INTO ressoa_schema VALUES (1) ON CONFLICT DO NOTHING')
        db.execute('INSERT INTO ressoa_schema VALUES (2) ON CONFLICT DO NOTHING')
        db.execute('INSERT INTO ressoa_schema VALUES (3) ON CONFLICT DO NOTHING')
        db.execute('INSERT INTO ressoa_schema VALUES (4) ON CONFLICT DO NOTHING')
