"""Account repository, with local SQLite or hosted PostgreSQL storage."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import uuid
import unicodedata
import regex
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def current_week():
    today = datetime.now(timezone(timedelta(hours=-3))).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def text(value, minimum=0, maximum=2400):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise APIError(400, 'Confira os campos e o tamanho do texto.')
    return value.strip()


_USERNAME_EMOJI = regex.compile(r'[\p{Extended_Pictographic}\p{Regional_Indicator}\p{Emoji_Modifier}\uFE0F\u20E3]')


def clean_username(value):
    if not isinstance(value, str):
        raise APIError(400, 'Informe um nome de usuário.')
    value = unicodedata.normalize('NFC', value).strip().lstrip('@').strip()
    if not 1 <= len(value) <= 24:
        raise APIError(400, 'Use de 1 a 24 caracteres no nome de usuário.')
    if _USERNAME_EMOJI.search(value):
        raise APIError(400, 'O nome de usuário não pode conter emojis.')
    if not value.isprintable():
        raise APIError(400, 'Use apenas caracteres visíveis no nome de usuário.')
    return value


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


_DUMMY = password_hash('dummy-password-not-an-account')


def check_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return algorithm == 'pbkdf2_sha256' and hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def clean_track(value):
    if not isinstance(value, dict):
        raise APIError(400, 'Selecione uma música.')
    identifier = value.get('catalogId', '')
    if not re.fullmatch(r'spotify:[A-Za-z0-9]{22}|deezer:[0-9]{1,16}', identifier):
        raise APIError(400, 'Música inválida.')
    provider, track_id = identifier.split(':')

    def asset(key, hosts):
        url = value.get(key, '')
        parsed = urlparse(url) if isinstance(url, str) else None
        if parsed and parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and any(parsed.hostname == host or parsed.hostname.endswith('.' + host) for host in hosts):
            return url[:2000]
        return ''

    duration = value.get('duration', 0)
    contributors = value.get('contributors', [])
    return dict(catalogId=identifier, provider=provider, spotifyId=track_id if provider == 'spotify' else '',
                title=text(value.get('title'), 1, 240), artist=text(value.get('artist'), 1, 180),
                album=text(value.get('album', ''), 0, 180), year=str(value.get('year', ''))[:4],
                duration=min(max(duration, 0), 86400) if isinstance(duration, (int, float)) else 0,
                artwork=asset('artwork', ['dzcdn.net', 'spotifycdn.com', 'scdn.co']), previewUrl=asset('previewUrl', ['dzcdn.net']),
                releaseDate=value.get('releaseDate', '') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(value.get('releaseDate', ''))) else '',
                trackReleaseDate=value.get('trackReleaseDate', '') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(value.get('trackReleaseDate', ''))) else '',
                contributors=[name[:180] for name in contributors[:15] if isinstance(name,str)] if isinstance(contributors,list) else [],
                bpm=min(max(value.get('bpm',0),0),400) if isinstance(value.get('bpm'),(int,float)) else 0,
                isrc=value.get('isrc','') if re.fullmatch(r'[A-Za-z0-9]{12}', str(value.get('isrc',''))) else '',
                explicit=value.get('explicit') if isinstance(value.get('explicit'),bool) else None,
                url=f'https://open.spotify.com/track/{track_id}' if provider == 'spotify' else f'https://www.deezer.com/track/{track_id}')


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, username TEXT NOT NULL UNIQUE COLLATE BINARY,
 password_hash TEXT NOT NULL, display_name TEXT NOT NULL, bio TEXT NOT NULL DEFAULT '', photo TEXT NOT NULL DEFAULT '',
 favorites TEXT NOT NULL DEFAULT '[]', pinned TEXT NOT NULL DEFAULT '[]', background TEXT,
 entries_version INTEGER NOT NULL DEFAULT 0, profile_version INTEGER NOT NULL DEFAULT 0,
 draft TEXT NOT NULL DEFAULT '{}', seen TEXT NOT NULL DEFAULT '{}', imported_at TEXT, created_at TEXT NOT NULL,
 is_private INTEGER NOT NULL DEFAULT 0, notifications_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS password_resets (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS password_resets_expiry ON password_resets(expires_at);
CREATE TABLE IF NOT EXISTS tracks (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 track_id TEXT NOT NULL REFERENCES tracks(id), text TEXT NOT NULL, visibility TEXT NOT NULL,
 kind TEXT NOT NULL DEFAULT 'entry', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 lyric_excerpt TEXT NOT NULL DEFAULT '', feed_published_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS posts_owner ON posts(owner_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS posts_public ON posts(visibility, created_at DESC);
CREATE TABLE IF NOT EXISTS weekly (
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, week_key TEXT NOT NULL,
 post_id TEXT REFERENCES posts(id) ON DELETE SET NULL, selected_at TEXT NOT NULL, deleted_at TEXT,
 PRIMARY KEY(user_id, week_key)
);
CREATE TABLE IF NOT EXISTS follows (user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, target_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, PRIMARY KEY(user_id, target_id));
CREATE TABLE IF NOT EXISTS follow_requests (
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, target_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL, PRIMARY KEY(user_id,target_id)
);
CREATE INDEX IF NOT EXISTS follow_requests_target ON follow_requests(target_id,created_at);
CREATE TABLE IF NOT EXISTS follow_notifications (
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, actor_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL, read_at TEXT, PRIMARY KEY(user_id,actor_id)
);
CREATE INDEX IF NOT EXISTS follow_notifications_recent ON follow_notifications(user_id,created_at DESC,actor_id DESC);
CREATE INDEX IF NOT EXISTS follow_notifications_unread ON follow_notifications(user_id) WHERE read_at IS NULL;
CREATE TABLE IF NOT EXISTS actions (
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('like','repost','saved')), PRIMARY KEY(user_id, post_id, kind)
);
CREATE INDEX IF NOT EXISTS actions_post ON actions(post_id,kind,user_id);
CREATE INDEX IF NOT EXISTS follows_target ON follows(target_id,user_id);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, reset_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS shares (
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 method TEXT NOT NULL CHECK(method IN ('native','link')), updated_at TEXT NOT NULL,
 PRIMARY KEY(user_id,post_id)
);
PRAGMA user_version = 6;
"""


class Connection(sqlite3.Connection):
    def fetch_many(self, queries):
        return [self.execute(statement, parameters).fetchall() for statement, parameters in queries]

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Database:
    def __init__(self, path):
        self.source=path
        self._request_state = ContextVar('ressoa_database_request', default=None)
        self.is_postgres=str(path).startswith(('postgres://','postgresql://'))
        self.username_match = 'username COLLATE "C"=?' if self.is_postgres else 'username COLLATE BINARY=?'
        if self.is_postgres:
            from postgres_storage import initialize, create_pool
            self.path=None;self._dsn=str(path)
            initialize(self._dsn,SCHEMA)
            self._pool=create_pool(self._dsn)
            return
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            for table,column,definition in (('users','is_private','INTEGER NOT NULL DEFAULT 0'),('users','notifications_version','INTEGER NOT NULL DEFAULT 0'),('posts','lyric_excerpt',"TEXT NOT NULL DEFAULT ''"),('posts','feed_published_at',"TEXT NOT NULL DEFAULT ''")):
                if column not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
            self._migrate_username_case(db)

    @staticmethod
    def _migrate_username_case(db):
        definition = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
        pattern = r'(\busername\s+TEXT\s+NOT\s+NULL\s+UNIQUE\s+COLLATE\s+)NOCASE'
        if not re.search(pattern, definition, re.IGNORECASE):
            return
        # Rebuild only the local users table, preserving IDs and every child row.
        # Foreign keys are checked before the transaction commits.
        db.execute('PRAGMA foreign_keys=OFF')
        if db.execute('PRAGMA foreign_keys').fetchone()[0]:
            raise RuntimeError('A atualização local dos nomes precisa iniciar fora de uma transação.')
        try:
            db.execute('BEGIN IMMEDIATE')
            definition = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
            updated = re.sub(pattern, r'\1BINARY', definition, flags=re.IGNORECASE)
            if updated != definition:
                updated = re.sub(r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:"users"|users)', 'CREATE TABLE "__ressoa_users_exact"', updated, count=1, flags=re.IGNORECASE)
                objects = db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='users' AND type IN ('index','trigger') AND sql IS NOT NULL AND name NOT IN ('users_username_ci','users_username_unicode_ci')").fetchall()
                columns = ','.join('"'+row['name'].replace('"','""')+'"' for row in db.execute('PRAGMA table_info(users)').fetchall())
                db.execute(updated)
                db.execute(f'INSERT INTO "__ressoa_users_exact" ({columns}) SELECT {columns} FROM users')
                db.execute('DROP TABLE users')
                db.execute('ALTER TABLE "__ressoa_users_exact" RENAME TO users')
                for item in objects:
                    db.execute(item['sql'])
                if db.execute('PRAGMA foreign_key_check').fetchall():
                    raise RuntimeError('Não foi possível atualizar os nomes de usuário mantendo os vínculos das contas.')
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute('PRAGMA foreign_keys=ON')

    @staticmethod
    def clean_excerpt(value):
        value=text(value,0,120)
        if len(value.splitlines())>3:
            raise APIError(400,'Escolha até 3 versos para o trecho.')
        return value

    @staticmethod
    def can_view_profile(db,viewer_id,target_id):
        if viewer_id==target_id:return True
        return bool(db.execute('SELECT 1 FROM users u WHERE u.id=? AND (u.is_private=0 OR EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=u.id))',(target_id,viewer_id)).fetchone())

    @staticmethod
    def visible_author_sql(viewer_id):
        # All queries using this condition alias posts as p and their owner as u.
        return '(u.is_private=0 OR p.owner_id=? OR EXISTS(SELECT 1 FROM follows access WHERE access.user_id=? AND access.target_id=p.owner_id))',(viewer_id,viewer_id)

    @contextmanager
    def request_scope(self):
        if not self.is_postgres or self._request_state.get() is not None:
            yield
            return
        state = {}
        token = self._request_state.set(state)
        try:
            yield
        finally:
            self._request_state.reset(token)
            if state.get('connection') is not None:
                state['connection'].close()

    def connect(self):
        if self.is_postgres:
            from postgres_storage import PostgresConnection, ConnectionLease
            state = self._request_state.get()
            if state is None:
                return PostgresConnection(self._dsn, self._pool)
            if 'connection' not in state:
                state['connection'] = PostgresConnection(self._dsn, self._pool)
            return ConnectionLease(state['connection'])
        db = sqlite3.connect(self.path, timeout=15, factory=Connection)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.create_function('username_key', 1, lambda value: unicodedata.normalize('NFC',value).lower() if isinstance(value,str) else None, deterministic=True)
        db.create_function('search_key',1,lambda value: ''.join(character for character in unicodedata.normalize('NFKD',str(value or '')).casefold() if not unicodedata.combining(character)),deterministic=True)
        db._track_cache={};db._person_cache={}
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            if self.is_postgres:
                from postgres_storage import WRITE_LOCK
                db.execute('BEGIN')
                # Preserve the existing atomic-write semantics during the first hosted release.
                db.execute('SELECT pg_advisory_xact_lock(?)',(WRITE_LOCK,))
            else:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def limit(self, key, maximum=15, seconds=900):
        key, now = hashlib.sha256(key.encode()).hexdigest(), time.time()
        # One atomic statement locks only this counter, without the application write lock.
        with self.connect() as db:
            count = db.execute('''INSERT INTO rate_limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET
                count=CASE WHEN rate_limits.reset_at < ? THEN 1 ELSE rate_limits.count+1 END,
                reset_at=CASE WHEN rate_limits.reset_at < ? THEN ? ELSE rate_limits.reset_at END
                RETURNING count''', (key,now+seconds,now,now,now+seconds)).fetchone()[0]
        if count > maximum:
            raise APIError(429, 'Muitas tentativas. Aguarde alguns minutos antes de tentar novamente.')

    def register(self, data):
        email = text(data.get('email'), 5, 254).lower()
        username, name = clean_username(data.get('username')), text(data.get('displayName'), 2, 50)
        password = data.get('password')
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise APIError(400, 'Use uma senha de 10 a 128 caracteres.')
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise APIError(400, 'Confira o e-mail.')
        self.check_registration(email, username)
        encoded, user_id = password_hash(password), str(uuid.uuid4())
        try:
            with self.transaction() as db:
                self.check_registration(email, username, db)
                db.execute('INSERT INTO users (id,email,username,password_hash,display_name,created_at) VALUES (?,?,?,?,?,?)', (user_id, email, username, encoded, name, now_iso()))
        except sqlite3.IntegrityError:
            # The UNIQUE constraints also protect simultaneous registrations.
            self.check_registration(email, username)
            raise APIError(409, 'Não foi possível criar a conta. Confira o e-mail e o usuário.')
        return user_id

    def check_registration(self, email, username, db=None):
        if db is None:
            with self.connect() as db:
                return self.check_registration(email, username, db)
        # Login accepts either field, so another account cannot reuse either identity.
        email_used = bool(db.execute('SELECT 1 FROM users WHERE username_key(email)=username_key(?) OR username_key(username)=username_key(?)', (email,email)).fetchone())
        username_used = bool(db.execute(f'SELECT 1 FROM users WHERE {self.username_match} OR username_key(email)=username_key(?)', (username,username)).fetchone())
        if email_used and username_used:
            raise APIError(409, 'Esse e-mail e esse nome de usuário já estão em uso. Insira outro e-mail e outro usuário.')
        if email_used:
            raise APIError(409, 'Esse e-mail já está em uso. Entre na sua conta ou insira outro e-mail.')
        if username_used:
            raise APIError(409, 'Esse nome de usuário já está em uso. Escolha outro para continuar.')

    def login(self, data):
        identifier, password = unicodedata.normalize('NFC',text(data.get('identifier'), 1, 254)).lstrip('@').strip(), data.get('password', '')
        if not isinstance(password, str) or len(password) > 128:
            raise APIError(401, 'E-mail, usuário ou senha incorretos.')
        with self.connect() as db:
            row = db.execute(f'SELECT id,password_hash FROM users WHERE {self.username_match} OR username_key(email)=username_key(?)', (identifier, identifier)).fetchone()
        self.limit('login:' + (row['id'] if row else identifier))
        valid = check_password(password, row['password_hash'] if row else _DUMMY)
        if not row or not valid:
            raise APIError(401, 'E-mail, usuário ou senha incorretos.')
        return row['id']

    def create_session(self, user_id, remember):
        token = secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute('DELETE FROM sessions WHERE expires_at < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user_id, time.time() + (30 if remember else 1) * 86400))
        return token

    def session_user(self, token):
        with self.connect() as db:
            row = db.execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return row['user_id'] if row else None

    def logout(self, token):
        with self.transaction() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def request_password_reset(self, email):
        token = secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute('DELETE FROM password_resets WHERE expires_at<=?', (time.time(),))
            user = db.execute('SELECT id,email FROM users WHERE username_key(email)=username_key(?)', (email,)).fetchone()
            if not user:
                return None
            db.execute('''INSERT INTO password_resets VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                token_hash=excluded.token_hash,expires_at=excluded.expires_at''',
                (hashlib.sha256(token.encode()).hexdigest(), user['id'], time.time()+1800))
        return dict(email=user['email'], token=token)

    def discard_password_reset(self, token):
        with self.transaction() as db:
            db.execute('DELETE FROM password_resets WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def reset_password(self, data):
        token, password = data.get('token'), data.get('password')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise APIError(400, 'Esse link é inválido ou expirou. Solicite outro link.')
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise APIError(400, 'Use uma senha de 10 a 128 caracteres.')
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM password_resets WHERE token_hash=? AND expires_at>?', (token_hash,time.time())).fetchone():
                raise APIError(400, 'Esse link é inválido ou expirou. Solicite outro link.')
        encoded = password_hash(password)
        with self.transaction() as db:
            # Consuming the token and replacing the password must succeed together.
            user = db.execute('DELETE FROM password_resets WHERE token_hash=? AND expires_at>? RETURNING user_id', (token_hash,time.time())).fetchone()
            if not user:
                raise APIError(400, 'Esse link é inválido ou expirou. Solicite outro link.')
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded,user['user_id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user['user_id'],))

    @staticmethod
    def store_track(db, value):
        track = clean_track(value)
        db.execute('INSERT INTO tracks VALUES (?,?) ON CONFLICT DO NOTHING', (track['catalogId'], json.dumps(track)))
        return track['catalogId']

    @staticmethod
    def track(db, identifier):
        if identifier in db._track_cache:return db._track_cache[identifier]
        row = db.execute('SELECT data FROM tracks WHERE id=?', (identifier,)).fetchone()
        result=json.loads(row['data']) if row else None
        if result:db._track_cache[identifier]=result
        return result

    def prime_posts(self, db, rows, extra_tracks=()):
        owners={row['owner_id'] for row in rows}-db._person_cache.keys()
        identifiers=({row['track_id'] for row in rows}|{key for key in extra_tracks if key})-db._track_cache.keys()
        if owners:
            marks=','.join('?' for _ in owners)
            for row in db.execute(f'SELECT id,display_name,username,photo,is_private FROM users WHERE id IN ({marks})',tuple(owners)).fetchall():db._person_cache[row['id']]=row
        if identifiers:
            marks=','.join('?' for _ in identifiers)
            for row in db.execute(f'SELECT id,data FROM tracks WHERE id IN ({marks})',tuple(identifiers)).fetchall():db._track_cache[row['id']]=json.loads(row['data'])

    def cache_verified_track(self, value):
        track=clean_track(value)
        with self.transaction() as db:
            db.execute('INSERT INTO tracks VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(track['catalogId'],json.dumps(track)))

    @staticmethod
    def person(row):
        return dict(id=row['id'],displayName=row['display_name'],handle=row['username'],photo=row['photo'])

    def search_people(self, viewer_id, query):
        query=text(query.lstrip('@') if isinstance(query,str) else query,1,80)
        with self.connect() as db:
            normalized=db.execute('SELECT search_key(?)',(query,)).fetchone()[0]
            literal=normalized.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            rows=db.execute(r"""SELECT id,display_name,username,photo FROM users
                WHERE search_key(username) LIKE ? ESCAPE '\' OR search_key(display_name) LIKE ? ESCAPE '\'
                ORDER BY CASE WHEN search_key(username)=? THEN 0 WHEN search_key(username) LIKE ? ESCAPE '\' THEN 1
                              WHEN search_key(display_name) LIKE ? ESCAPE '\' THEN 2 ELSE 3 END,
                    EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=users.id) DESC,username LIMIT 20""",
                ('%'+literal+'%','%'+literal+'%',normalized,literal+'%',literal+'%',viewer_id)).fetchall()
            return [self.person(row) for row in rows]

    def public_profile(self, viewer_id, target_id, offset=0, repost_offset=0):
        if not isinstance(target_id,str) or len(target_id)>100:
            raise APIError(404,'Perfil não encontrado.')
        if not 0<=offset<=5000 or not 0<=repost_offset<=5000:
            raise APIError(400,'Página inválida.')
        with self.connect() as db:
            db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.is_postgres else 'BEGIN')
            user=db.execute('SELECT id,display_name,username,bio,photo,favorites,pinned,background,is_private FROM users WHERE id=?',(target_id,)).fetchone()
            if not user:
                raise APIError(404,'Esse perfil não foi encontrado.')
            can_view=self.can_view_profile(db,viewer_id,target_id)
            following=bool(db.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(viewer_id,target_id)).fetchone())
            requested=bool(db.execute('SELECT 1 FROM follow_requests WHERE user_id=? AND target_id=?',(viewer_id,target_id)).fetchone())
            state='following' if following else 'requested' if requested else 'none'
            if not can_view:
                return dict(id=target_id,canView=False,canViewRelations=False,followState=state,
                    profile=dict(displayName=user['display_name'],handle=user['username'],bio=user['bio'],photo=user['photo'],isPrivate=True,favorites=[],pinned=[],background=None),
                    entries=[],reposts=[],weekly=None,nextEntriesOffset=None,nextRepostsOffset=None)
            # Check pins again on the server; never reveal IDs of private entries.
            wanted=json.loads(user['pinned'])
            public_ids={row['id'] for row in db.execute("SELECT id FROM posts WHERE owner_id=? AND visibility='public' AND kind='entry'",(target_id,)).fetchall()}
            pinned=[identifier for identifier in wanted if identifier in public_ids]
            placeholders=','.join('?' for _ in pinned) or 'NULL'
            rows=db.execute(f"""SELECT * FROM posts WHERE owner_id=? AND visibility='public' AND kind='entry'
                ORDER BY CASE WHEN id IN ({placeholders}) THEN 0 ELSE 1 END,created_at DESC,id DESC LIMIT 25 OFFSET ?""",
                (target_id,*pinned,offset)).fetchall()
            access,access_params=self.visible_author_sql(viewer_id)
            reposted=db.execute(f"""SELECT p.* FROM posts p JOIN actions a ON a.post_id=p.id JOIN users u ON u.id=p.owner_id WHERE a.user_id=? AND a.kind='repost' AND p.visibility='public' AND {access}
                AND (p.kind='entry' OR EXISTS(SELECT 1 FROM weekly w WHERE w.post_id=p.id AND w.week_key=? AND w.deleted_at IS NULL))
                ORDER BY p.created_at DESC,p.id DESC LIMIT 25 OFFSET ?""",(target_id,*access_params,current_week(),repost_offset)).fetchall()
            selection=db.execute('SELECT p.* FROM posts p JOIN weekly w ON w.post_id=p.id WHERE w.user_id=? AND w.week_key=? AND w.deleted_at IS NULL AND p.visibility=\'public\'',(target_id,current_week())).fetchone()
            self.prime_posts(db,[*rows,*reposted,*([selection] if selection else [])],[*json.loads(user['favorites']),user['background']])
            profile=dict(displayName=user['display_name'],handle=user['username'],bio=user['bio'],photo=user['photo'],
                         isPrivate=bool(user['is_private']),favorites=[track for key in json.loads(user['favorites']) if (track:=self.track(db,key))],pinned=pinned,background=self.track(db,user['background']))
            return dict(id=target_id,profile=profile,canView=True,canViewRelations=viewer_id==target_id or (not user['is_private'] and following),followState=state,entries=[self.post(db,row) for row in rows[:24]],
                        reposts=[self.post(db,row) for row in reposted[:24]],weekly=self.post(db,selection),
                        nextEntriesOffset=offset+24 if len(rows)>24 else None,nextRepostsOffset=repost_offset+24 if len(reposted)>24 else None)

    def post(self, db, row):
        if not row:
            return None
        owner=db._person_cache.get(row['owner_id'])
        if owner is None:
            owner=db.execute('SELECT display_name,username,photo,is_private FROM users WHERE id=?',(row['owner_id'],)).fetchone()
            db._person_cache[row['owner_id']]=owner
        published=row['feed_published_at'] or row['created_at']
        week_end=(datetime.fromisoformat(current_week()).replace(tzinfo=timezone(timedelta(hours=-3)))+timedelta(days=7)).astimezone(timezone.utc).isoformat() if row['kind']=='weekly' else None
        return dict(id=row['id'], ownerId=row['owner_id'], author=owner['display_name'], handle=owner['username'], photo=owner['photo'],
                    initials=owner['display_name'][:2].upper(), track=self.track(db, row['track_id']), text=row['text'], visibility=row['visibility'],
                    kind=row['kind'], createdAt=row['created_at'], updatedAt=row['updated_at'],publishedAt=published,feedExpiresAt=week_end,lyricExcerpt=row['lyric_excerpt'],authorPrivate=bool(owner['is_private']))

    def accessible(self, db, user_id, post_id, public=False):
        visibility = " AND p.visibility='public'" if public else ''
        row = db.execute(f'''SELECT p.*,t.data AS track_data,u.display_name AS owner_name,
            u.username AS owner_handle,u.photo AS owner_photo,u.is_private AS owner_private,
            EXISTS(SELECT 1 FROM weekly w WHERE w.post_id=p.id AND w.week_key=? AND w.deleted_at IS NULL) AS active_week
            FROM posts p JOIN users u ON u.id=p.owner_id JOIN tracks t ON t.id=p.track_id
            WHERE p.id=? AND (p.owner_id=? OR p.visibility='public') AND
                (u.is_private=0 OR p.owner_id=? OR EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=p.owner_id)){visibility}''',
            (current_week(),post_id,user_id,user_id,user_id)).fetchone()
        if not row:
            raise APIError(404, 'Ressoa não encontrada.')
        if row['kind'] == 'weekly' and not row['active_week']:
            raise APIError(404, 'Este destaque já terminou.')
        db._track_cache[row['track_id']]=json.loads(row['track_data'])
        db._person_cache[row['owner_id']]=dict(display_name=row['owner_name'],username=row['owner_handle'],photo=row['owner_photo'],is_private=row['owner_private'])
        return row

    def shared_post(self, user_id, post_id):
        with self.connect() as db:
            row = self.accessible(db, user_id, text(post_id, 1, 100))
            return self.post(db, row)

    @staticmethod
    def clean_seen(value):
        if not isinstance(value, dict) or len(value)>300:
            raise APIError(400, 'Histórico inválido.')
        now = time.time()*1000
        return {key:stamp for key,stamp in value.items() if isinstance(key,str) and len(key)<=100
                and type(stamp) in (int,float) and now-7*86400000<stamp<=now+60000}

    def feed_query(self, user_id, mode, seen):
        if mode not in ('foryou','following'):
            raise APIError(400, 'Feed inválido.')
        seen = self.clean_seen(seen)
        values = ','.join('(?,?)' for _ in seen) or '(NULL,NULL)'
        parameters = [part for item in seen.items() for part in item]
        published = "COALESCE(NULLIF(p.feed_published_at,''),p.created_at)"
        stamp = f'EXTRACT(EPOCH FROM CAST({published} AS timestamptz))*1000' if self.is_postgres else f"(julianday({published})-2440587.5)*86400000"
        access, access_params = self.visible_author_sql(user_id)
        followed = 'EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=p.owner_id)'
        restriction = f' AND {followed}' if mode=='following' else ''
        cutoff = (datetime.now(timezone.utc)-timedelta(days=1)).timestamp()*1000
        statement = f'''WITH viewed(id,seen_at) AS (VALUES {values})
            SELECT p.* FROM posts p JOIN users u ON u.id=p.owner_id LEFT JOIN viewed v ON v.id=p.id
            WHERE p.visibility='public' AND p.owner_id<>? AND {access}{restriction}
            AND (p.kind='weekly' OR {stamp}>?)
            AND (p.kind='entry' OR EXISTS(SELECT 1 FROM weekly w WHERE w.post_id=p.id AND w.week_key=? AND w.deleted_at IS NULL))
            ORDER BY CASE WHEN CAST(v.seen_at AS DOUBLE PRECISION)>={stamp} THEN 1 ELSE 0 END,
                CASE WHEN CAST(v.seen_at AS DOUBLE PRECISION)>={stamp} THEN CAST(v.seen_at AS DOUBLE PRECISION) ELSE 0 END,
                {stamp} DESC,{followed} DESC,p.id LIMIT 120'''
        parameters.extend((user_id,*access_params,*([user_id] if mode=='following' else []),cutoff,current_week(),user_id))
        return statement, tuple(parameters)

    def bootstrap(self, user_id, feed_options=None):
        with self.connect() as db:
            db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.is_postgres else 'BEGIN')
            access,access_params=self.visible_author_sql(user_id)
            published="COALESCE(NULLIF(p.feed_published_at,''),p.created_at)"
            published_time=f"CAST({published} AS timestamptz)" if self.is_postgres else f"julianday({published})"
            recent=f"{published_time}>CAST(? AS timestamptz)" if self.is_postgres else f"{published_time}>julianday(?)"
            cutoff=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
            queries = [
                ('''SELECT users.*,(SELECT COUNT(*) FROM follow_notifications n WHERE n.user_id=users.id AND n.read_at IS NULL AND n.created_at>?) AS unread_followers
                    FROM users WHERE id=?''', (self.notification_cutoff(),user_id)),
                ("SELECT * FROM posts WHERE owner_id=? AND kind='entry' ORDER BY created_at DESC", (user_id,)),
                (f"""SELECT p.* FROM posts p JOIN users u ON u.id=p.owner_id WHERE p.visibility='public' AND p.owner_id<>? AND {access}
                AND (p.kind='weekly' OR {recent})
                AND (p.kind='entry' OR EXISTS(SELECT 1 FROM weekly w WHERE w.post_id=p.id AND w.week_key=? AND w.deleted_at IS NULL))
                ORDER BY {published_time} DESC,EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=p.owner_id) DESC,p.id LIMIT 120""", (user_id,*access_params,cutoff,current_week(), user_id)),
                (f"""SELECT DISTINCT p.* FROM posts p JOIN actions a ON p.id=a.post_id JOIN users u ON u.id=p.owner_id WHERE a.user_id=? AND (p.visibility='public' OR p.owner_id=?) AND {access}
                AND (p.kind='entry' OR EXISTS(SELECT 1 FROM weekly w WHERE w.post_id=p.id AND w.week_key=? AND w.deleted_at IS NULL)) LIMIT 500""", (user_id,user_id,*access_params,current_week())),
                ('SELECT * FROM weekly WHERE user_id=? AND week_key=?', (user_id,current_week())),
                (f"""SELECT a.* FROM actions a JOIN posts p ON p.id=a.post_id JOIN users u ON u.id=p.owner_id
                WHERE a.user_id=? AND (p.visibility='public' OR p.owner_id=?) AND {access}
                AND (p.kind='entry' OR EXISTS(SELECT 1 FROM weekly w WHERE w.post_id=p.id AND w.week_key=? AND w.deleted_at IS NULL))""", (user_id,user_id,*access_params,current_week())),
                ('SELECT u.id,u.display_name,u.username,u.photo FROM users u JOIN follows f ON f.target_id=u.id WHERE f.user_id=?', (user_id,)),
                ('SELECT u.id,u.display_name,u.username,u.photo FROM users u JOIN follows f ON f.user_id=u.id WHERE f.target_id=? ORDER BY u.display_name,u.id', (user_id,)),
                ('SELECT u.id,u.display_name,u.username,u.photo,r.created_at FROM follow_requests r JOIN users u ON u.id=r.user_id WHERE r.target_id=? ORDER BY r.created_at,u.id', (user_id,)),
                ('SELECT target_id FROM follow_requests WHERE user_id=?', (user_id,)),
            ]
            # Keep a separate pool for Following even when discovery has 120 newer posts.
            queries.append(self.feed_query(user_id,'following',{}))
            if feed_options is not None:
                queries.append(self.feed_query(user_id,feed_options.get('mode'),feed_options.get('seen',{})))
            results = db.fetch_many(queries)
            users,own,public,extra,selections,actions,following,followers,request_rows,requested_rows = results[:10]
            public = [*public,*results[10]]
            if feed_options is not None:
                public = [*public,*results[11]]
            user = users[0]
            shared = {row['id']: row for row in [*public, *extra] if row['owner_id'] != user_id}
            selection = selections[0] if selections else None
            weekly = None
            if selection:
                item = db.execute('SELECT * FROM posts WHERE id=?', (selection['post_id'],)).fetchone()
                weekly = dict(postId=selection['post_id'] or 'deleted', item=self.post(db, item), weekKey=selection['week_key'], selectedAt=selection['selected_at'], deletedAt=selection['deleted_at'])
            requests=[dict(self.person(row),requestedAt=row['created_at']) for row in request_rows]
            requested=[row['target_id'] for row in requested_rows]
            self.prime_posts(db,[*own,*public,*extra,*([item] if selection and item else [])],[*json.loads(user['favorites']),user['background']])
            return dict(user=dict(id=user_id, email=user['email'], username=user['username']),
                        profile=dict(displayName=user['display_name'], handle=user['username'], bio=user['bio'], photo=user['photo'],isPrivate=bool(user['is_private']), favorites=[self.track(db, key) for key in json.loads(user['favorites'])], pinned=json.loads(user['pinned']), background=self.track(db, user['background'])),
                        entries=[self.post(db, row) for row in own], publicPosts=[self.post(db, row) for row in shared.values()], weekly=weekly,
                        saved=[row['post_id'] for row in actions if row['kind'] == 'saved'],
                        social=dict(following=[row['id'] for row in following],requested=requested, reposts=[row['post_id'] for row in actions if row['kind'] == 'repost'], likes={row['post_id']: ['me'] for row in actions if row['kind'] == 'like'}, seen=json.loads(user['seen'])),
                        followingPeople=[dict(id=row['id'], displayName=row['display_name'], handle=row['username'], photo=row['photo']) for row in following],
                        followersPeople=[self.person(row) for row in followers],followRequests=requests,
                        notifications=dict(version=user['notifications_version'],unreadFollowers=user['unread_followers'],requestCount=len(requests),unreadCount=user['unread_followers']+len(requests)),
                        draft=json.loads(user['draft']), importedAt=user['imported_at'], serverWeek=current_week(), versions=dict(entries=user['entries_version'], profile=user['profile_version']))

    def save_entries(self, user_id, data):
        items = data.get('value')
        if not isinstance(items, list) or len(items) > 3000:
            raise APIError(400, 'Lista de ressoas inválida.')
        republish_id=data.get('republish')
        if republish_id is not None and (not isinstance(republish_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',republish_id)):
            raise APIError(400,'Ressoa para republicar inválido.')
        clear_draft = data.get('clearDraft', False)
        if type(clear_draft) is not bool:
            raise APIError(400, 'Opção de rascunho inválida.')
        with self.transaction() as db:
            user = db.execute('SELECT entries_version,pinned FROM users WHERE id=?', (user_id,)).fetchone()
            if data.get('version') != user['entries_version']:
                raise APIError(409, 'Seu diário mudou em outro dispositivo. Atualizamos os dados; tente novamente.')
            previous = {row['id']: row for row in db.execute("SELECT * FROM posts WHERE owner_id=? AND kind='entry'", (user_id,)).fetchall()}
            ids = set()
            for item in items:
                if not isinstance(item, dict):
                    raise APIError(400, 'Ressoa inválida.')
                post_id = text(item.get('id'), 1, 100)
                if not re.fullmatch(r'[A-Za-z0-9_-]+', post_id) or post_id in ids:
                    raise APIError(400, 'Identificador inválido ou repetido.')
                ids.add(post_id)
                existing = previous.get(post_id)
                if existing is None:
                    existing = db.execute('SELECT * FROM posts WHERE id=?', (post_id,)).fetchone()
                if existing and (existing['owner_id'] != user_id or existing['kind'] != 'entry'):
                    raise APIError(403, 'Você só pode alterar suas próprias ressoas.')
                track = clean_track(item.get('track'))
                track_id, message = track['catalogId'], text(item.get('text',''), 0, 2400)
                if not existing or existing['track_id'] != track_id:
                    self.store_track(db, track)
                excerpt=self.clean_excerpt(item.get('lyricExcerpt',existing['lyric_excerpt'] if existing and existing['track_id']==track_id else ''))
                visibility = item.get('visibility')
                if visibility not in ('public', 'private'):
                    raise APIError(400, 'Visibilidade inválida.')
                changed = not existing or any(existing[key] != value for key, value in [('track_id',track_id),('text',message),('visibility',visibility),('lyric_excerpt',excerpt)])
                timestamp = now_iso() if changed else existing['updated_at']
                if post_id==republish_id and (not existing or visibility!='public'):
                    raise APIError(400,'Só é possível republicar uma entrada existente do perfil.')
                if post_id==republish_id and not changed:
                    raise APIError(400,'Altere o Ressoa antes de postar de novo.')
                if not changed:
                    continue
                published=now_iso() if not existing or (visibility=='public' and existing['visibility']=='private') else existing['feed_published_at']
                if post_id==republish_id:published=now_iso()
                db.execute("INSERT INTO posts (id,owner_id,track_id,text,visibility,kind,created_at,updated_at,lyric_excerpt,feed_published_at) VALUES (?,?,?,?,?,'entry',?,?,?,?) ON CONFLICT(id) DO UPDATE SET track_id=excluded.track_id,text=excluded.text,visibility=excluded.visibility,updated_at=excluded.updated_at,lyric_excerpt=excluded.lyric_excerpt,feed_published_at=excluded.feed_published_at", (post_id, user_id, track_id, message, visibility, existing['created_at'] if existing else timestamp, timestamp,excerpt,published))
                if existing and changed:
                    db.execute("DELETE FROM actions WHERE post_id=? AND kind IN ('like','repost')",(post_id,))
                    db.execute('DELETE FROM shares WHERE post_id=?',(post_id,))
                if visibility == 'private':
                    db.execute('DELETE FROM actions WHERE post_id=? AND user_id<>?', (post_id, user_id))
            if republish_id is not None and republish_id not in ids:
                raise APIError(400,'O Ressoa para republicar não está nesta edição.')
            for identifier in previous.keys() - ids:
                db.execute('DELETE FROM posts WHERE id=?', (identifier,))
            pinned = json.loads(user['pinned'])
            public_ids = {item['id'] for item in items if item.get('visibility') == 'public'}
            clean_pins = [key for key in pinned if key in public_ids]
            db.execute("UPDATE users SET entries_version=entries_version+1,pinned=?,profile_version=profile_version+?,draft=CASE WHEN ? THEN '{}' ELSE draft END WHERE id=?", (json.dumps(clean_pins), int(clean_pins != pinned), clear_draft, user_id))

    def save_profile(self, user_id, data):
        value = data.get('value')
        if not isinstance(value, dict):
            raise APIError(400, 'Perfil inválido.')
        name, handle = text(value.get('displayName'), 2, 50), clean_username(value.get('handle'))
        photo = value.get('photo', '')
        if not isinstance(photo, str) or len(photo) > 200_000 or (photo and not re.fullmatch(r'data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+', photo)):
            raise APIError(400, 'Foto inválida. Escolha uma imagem menor.')
        if photo:
            try:
                raw = base64.b64decode(photo.split(',', 1)[1], validate=True)
                if not raw.startswith((b'\xff\xd8\xff', b'\x89PNG\r\n\x1a\n', b'RIFF')):
                    raise ValueError()
            except ValueError:
                raise APIError(400, 'Imagem inválida.')
        favorites, pinned = value.get('favorites', []), value.get('pinned', [])
        if not isinstance(favorites, list) or len(favorites) > 6 or not isinstance(pinned, list) or len(pinned) > 100:
            raise APIError(400, 'Favoritas ou fixações inválidas.')
        with self.transaction() as db:
            current = db.execute('SELECT profile_version,is_private,username FROM users WHERE id=?', (user_id,)).fetchone()
            version=current['profile_version']
            if data.get('version') != version:
                raise APIError(409, 'Seu perfil mudou em outro dispositivo. Atualizamos os dados; tente novamente.')
            if handle != current['username'] and db.execute(f'SELECT 1 FROM users WHERE id<>? AND ({self.username_match} OR username_key(email)=username_key(?))', (user_id,handle,handle)).fetchone():
                raise APIError(409, 'Esse nome de usuário já está em uso. Escolha outro para continuar.')
            private=value.get('isPrivate',bool(current['is_private']))
            if type(private) is not bool:raise APIError(400,'Privacidade do perfil inválida.')
            favorite_ids = list(dict.fromkeys(self.store_track(db, item) for item in favorites))
            background = self.store_track(db, value['background']) if value.get('background') else None
            allowed_pins = []
            for identifier in pinned:
                if not isinstance(identifier, str):
                    raise APIError(400, 'Fixação inválida.')
                if db.execute("SELECT id FROM posts WHERE id=? AND owner_id=? AND visibility='public' AND kind='entry'", (identifier, user_id)).fetchone():
                    allowed_pins.append(identifier)
            try:
                db.execute('UPDATE users SET display_name=?,username=?,bio=?,photo=?,favorites=?,pinned=?,background=?,is_private=?,profile_version=profile_version+1 WHERE id=?', (name, handle, text(value.get('bio', ''), 0, 180), photo, json.dumps(favorite_ids), json.dumps(allowed_pins), background,int(private),user_id))
                if current['is_private'] and not private:
                    db.execute('''INSERT INTO follow_notifications(user_id,actor_id,created_at,read_at)
                        SELECT r.target_id,r.user_id,?,NULL FROM follow_requests r WHERE r.target_id=?
                        AND NOT EXISTS(SELECT 1 FROM follows f WHERE f.user_id=r.user_id AND f.target_id=r.target_id)
                        ON CONFLICT(user_id,actor_id) DO UPDATE SET created_at=excluded.created_at,read_at=NULL''',(now_iso(),user_id))
                    db.execute('INSERT INTO follows (user_id,target_id) SELECT user_id,target_id FROM follow_requests WHERE target_id=? ON CONFLICT DO NOTHING',(user_id,))
                    if db.execute('DELETE FROM follow_requests WHERE target_id=? RETURNING user_id',(user_id,)).fetchall():
                        self.bump_notifications(db,user_id)
            except sqlite3.IntegrityError:
                raise APIError(409, 'Esse nome de usuário já está em uso.')

    def choose_weekly(self, user_id, data):
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM weekly WHERE user_id=? AND week_key=?', (user_id, current_week())).fetchone():
                raise APIError(409, 'Você já usou a escolha desta semana. Uma nova será liberada na próxima segunda-feira.')
            track_id, message = self.store_track(db, data.get('track')), text(data.get('text', ''), 0, 2400)
            excerpt=self.clean_excerpt(data.get('lyricExcerpt',''))
            identifier, timestamp = str(uuid.uuid4()), now_iso()
            db.execute("INSERT INTO posts (id,owner_id,track_id,text,visibility,kind,created_at,updated_at,lyric_excerpt) VALUES (?,?,?,?,'public','weekly',?,?,?)", (identifier, user_id, track_id, message, timestamp, timestamp,excerpt))
            db.execute('INSERT INTO weekly VALUES (?,?,?,?,NULL)', (user_id, current_week(), identifier, timestamp))

    def delete_weekly(self, user_id):
        with self.transaction() as db:
            row = db.execute('SELECT post_id FROM weekly WHERE user_id=? AND week_key=?', (user_id, current_week())).fetchone()
            if row:
                db.execute('UPDATE weekly SET deleted_at=? WHERE user_id=? AND week_key=?', (now_iso(), user_id, current_week()))
                db.execute('DELETE FROM posts WHERE id=? AND owner_id=?', (row['post_id'], user_id))

    def action(self, user_id, kind, target, active):
        if type(active) is not bool or not isinstance(target, str):
            raise APIError(400, 'Interação inválida.')
        with self.transaction() as db:
            if kind == 'follow':
                person=db.execute('SELECT is_private FROM users WHERE id=?',(target,)).fetchone()
                if target == user_id or not person:
                    raise APIError(404, 'Pessoa não encontrada.')
                if active:
                    already=db.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(user_id,target)).fetchone()
                    if person['is_private'] and not already:
                        if db.execute('INSERT INTO follow_requests VALUES (?,?,?) ON CONFLICT DO NOTHING RETURNING user_id',(user_id,target,now_iso())).fetchone():
                            self.bump_notifications(db,target)
                    else:
                        self.add_follow(db,user_id,target)
                        if db.execute('DELETE FROM follow_requests WHERE user_id=? AND target_id=? RETURNING user_id',(user_id,target)).fetchone():
                            self.bump_notifications(db,target)
                else:
                    removed=db.fetch_many([
                        ('DELETE FROM follows WHERE user_id=? AND target_id=? RETURNING user_id',(user_id,target)),
                        ('DELETE FROM follow_requests WHERE user_id=? AND target_id=? RETURNING user_id',(user_id,target)),
                        ('DELETE FROM follow_notifications WHERE user_id=? AND actor_id=? RETURNING actor_id',(target,user_id))])
                    if any(removed):self.bump_notifications(db,target)
                return
            if kind not in ('like', 'repost', 'saved'):
                raise APIError(400, 'Interação inválida.')
            post = self.accessible(db, user_id, target, public=kind != 'saved')
            if kind == 'repost' and post['owner_id'] == user_id:
                raise APIError(400, 'Essa ressoa já está no seu perfil.')
            if active:
                db.execute('INSERT INTO actions VALUES (?,?,?) ON CONFLICT DO NOTHING', (user_id, target, kind))
            else:
                db.execute('DELETE FROM actions WHERE user_id=? AND post_id=? AND kind=?', (user_id, target, kind))
            return dict(action=dict(kind=kind,target=target,active=active),post=self.post(db,post))

    def follow_requests(self, db, user_id):
        rows=db.execute('SELECT u.id,u.display_name,u.username,u.photo,r.created_at FROM follow_requests r JOIN users u ON u.id=r.user_id WHERE r.target_id=? ORDER BY r.created_at,u.id',(user_id,)).fetchall()
        return [dict(self.person(row),requestedAt=row['created_at']) for row in rows]

    def requests_for(self,user_id):
        with self.connect() as db:return self.follow_requests(db,user_id)

    def respond_follow(self,user_id,data):
        requester=text(data.get('requester'),1,100)
        if type(data.get('accept')) is not bool:raise APIError(400,'Resposta inválida.')
        with self.transaction() as db:
            request=db.execute('''SELECT u.id,u.display_name,u.username,u.photo,u.is_private,r.created_at
                FROM follow_requests r JOIN users u ON u.id=r.user_id WHERE r.user_id=? AND r.target_id=?''',(requester,user_id)).fetchone()
            if not request or (data.get('createdAt') is not None and data['createdAt']!=request['created_at']):
                raise APIError(404,'Essa solicitação não está mais disponível.')
            timestamp=self.add_follow(db,requester,user_id,read=True) if data['accept'] else None
            db.execute('DELETE FROM follow_requests WHERE user_id=? AND target_id=?',(requester,user_id))
            self.bump_notifications(db,user_id)
            person=dict(self.person(request),isPrivate=bool(request['is_private']))
            return dict(followResponse=dict(person=person,accepted=data['accept'],
                notification=self.notification_item('follow',person,timestamp) if timestamp else None),
                summary=self.notification_summary(db.execute(*self.notification_summary_query(user_id)).fetchone()))

    def remove_follower(self,user_id,data):
        follower=text(data.get('user'),1,100)
        with self.transaction() as db:
            removed=db.fetch_many([
                ('DELETE FROM follows WHERE user_id=? AND target_id=? RETURNING user_id',(follower,user_id)),
                ('DELETE FROM follow_requests WHERE user_id=? AND target_id=? RETURNING user_id',(follower,user_id)),
                ('DELETE FROM follow_notifications WHERE user_id=? AND actor_id=? RETURNING actor_id',(user_id,follower))])
            if any(removed):self.bump_notifications(db,user_id)

    @staticmethod
    def bump_notifications(db,user_id):
        db.execute('UPDATE users SET notifications_version=notifications_version+1 WHERE id=?',(user_id,))

    def add_follow(self,db,actor_id,user_id,read=False):
        if not db.execute('INSERT INTO follows VALUES (?,?) ON CONFLICT DO NOTHING RETURNING user_id',(actor_id,user_id)).fetchone():
            return
        timestamp=now_iso()
        db.fetch_many([
            ('''INSERT INTO follow_notifications VALUES (?,?,?,?) ON CONFLICT(user_id,actor_id)
                DO UPDATE SET created_at=excluded.created_at,read_at=excluded.read_at RETURNING actor_id''',(user_id,actor_id,timestamp,timestamp if read else None)),
            ('UPDATE users SET notifications_version=notifications_version+1 WHERE id=? RETURNING id',(user_id,))])
        return timestamp

    @staticmethod
    def notification_cutoff():
        return (datetime.now(timezone.utc)-timedelta(days=7)).isoformat()

    @staticmethod
    def notification_item(kind,person,timestamp,unread=False):
        return dict(kind=kind,person=person,createdAt=timestamp,unread=unread,
            expiresAt=(datetime.fromisoformat(timestamp)+timedelta(days=7)).isoformat() if kind=='follow' else None)

    @staticmethod
    def notification_summary_query(user_id):
        return ('''SELECT notifications_version AS version,
            (SELECT COUNT(*) FROM follow_notifications n WHERE n.user_id=users.id AND n.read_at IS NULL AND n.created_at>?) AS unread_followers,
            (SELECT COUNT(*) FROM follow_requests r WHERE r.target_id=users.id) AS request_count FROM users WHERE id=?''',(Database.notification_cutoff(),user_id,))

    @staticmethod
    def notification_summary(row):
        return dict(version=row['version'],unreadFollowers=row['unread_followers'],requestCount=row['request_count'],unreadCount=row['unread_followers']+row['request_count'])

    def notifications(self,user_id,cursor='',summary_only=False):
        parameters=[user_id,user_id,self.notification_cutoff()]
        restriction=''
        if cursor:
            try:
                if not isinstance(cursor,str) or len(cursor)>600 or not re.fullmatch(r'[A-Za-z0-9_-]+',cursor):raise ValueError()
                values=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)).decode())
                if not isinstance(values,list) or len(values)!=3 or any(not isinstance(item,str) for item in values):raise ValueError()
                stamp,kind,actor=values
                if len(stamp)>50 or kind not in ('follow','request') or not 1<=len(actor)<=100 or not datetime.fromisoformat(stamp).tzinfo:raise ValueError()
            except (ValueError,UnicodeError,TypeError):
                raise APIError(400,'A lista mudou. Reabra as notificações.') from None
            restriction='WHERE (i.created_at,i.kind,i.actor_id)<(?,?,?)'
            parameters.extend(values)
        with self.connect() as db:
            db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.is_postgres else 'BEGIN')
            queries=[self.notification_summary_query(user_id)]
            if not summary_only:
                queries.append((f'''WITH items AS (
                    SELECT 'request' AS kind,user_id AS actor_id,created_at,NULL AS read_at FROM follow_requests WHERE target_id=?
                    UNION ALL SELECT 'follow',actor_id,created_at,read_at FROM follow_notifications WHERE user_id=? AND created_at>?)
                    SELECT i.kind,i.created_at,i.read_at,u.id,u.display_name,u.username,u.photo,u.is_private
                    FROM items i JOIN users u ON u.id=i.actor_id {restriction}
                    ORDER BY i.created_at DESC,i.kind DESC,i.actor_id DESC LIMIT 51''',tuple(parameters)))
            results=db.fetch_many(queries)
            summary=self.notification_summary(results[0][0])
            if summary_only:return dict(summary=summary)
            rows=results[1];items=[]
            for row in rows[:50]:
                items.append(self.notification_item(row['kind'],dict(self.person(row),isPrivate=bool(row['is_private'])),row['created_at'],row['kind']=='follow' and row['read_at'] is None))
            next_cursor=None
            if len(rows)>50:
                last=rows[49];payload=[last['created_at'],last['kind'],last['id']]
                next_cursor=base64.urlsafe_b64encode(json.dumps(payload,separators=(',',':')).encode()).decode().rstrip('=')
            return dict(summary=summary,items=items,nextCursor=next_cursor)

    def read_notifications(self,user_id,data):
        items=data.get('items')
        if not isinstance(items,list) or len(items)>50:raise APIError(400,'Notificações inválidas.')
        keys=[]
        for item in items:
            if not isinstance(item,dict):raise APIError(400,'Notificações inválidas.')
            keys.extend((text(item.get('actorId'),1,100),text(item.get('createdAt'),1,50)))
        if keys:
            values=','.join('(?,?)' for _ in items)
            with self.transaction() as db:
                changed=db.execute(f'''UPDATE follow_notifications SET read_at=? WHERE user_id=? AND read_at IS NULL
                    AND (actor_id,created_at) IN (VALUES {values}) RETURNING actor_id''',(now_iso(),user_id,*keys)).fetchall()
                if changed:self.bump_notifications(db,user_id)
        return self.notifications(user_id,summary_only=True)

    def dismiss_notification(self,user_id,data):
        actor=text(data.get('actorId'),1,100)
        timestamp=text(data.get('createdAt'),1,50)
        with self.transaction() as db:
            if db.execute('DELETE FROM follow_notifications WHERE user_id=? AND actor_id=? AND created_at=? RETURNING actor_id',(user_id,actor,timestamp)).fetchone():
                self.bump_notifications(db,user_id)
            return dict(summary=self.notification_summary(db.execute(*self.notification_summary_query(user_id)).fetchone()))

    def following_status(self,user_id,users):
        if not isinstance(users,str) or len(users)>5100:raise APIError(400,'Pessoas inválidas.')
        targets=list(dict.fromkeys(users.split(',')))
        if not 1<=len(targets)<=50 or any(not 1<=len(target)<=100 for target in targets):raise APIError(400,'Pessoas inválidas.')
        placeholders=','.join('?' for _ in targets)
        with self.connect() as db:
            rows=db.execute(f'''SELECT u.id,u.display_name,u.username,u.photo,
                CASE WHEN EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=u.id) THEN 'following'
                WHEN EXISTS(SELECT 1 FROM follow_requests r WHERE r.user_id=? AND r.target_id=u.id) THEN 'requested'
                ELSE 'none' END AS status FROM users u WHERE u.id IN ({placeholders})''',(user_id,user_id,*targets)).fetchall()
            people={row['id']:dict(person=self.person(row),status=row['status']) for row in rows}
            return dict(people=[people.get(target,dict(person=dict(id=target),status='none')) for target in targets])

    def likes(self, user_id, post_id):
        with self.connect() as db:
            post = self.accessible(db, user_id, post_id)
            if post['owner_id'] != user_id:
                raise APIError(403, 'Só o autor pode ver quem curtiu.')
            rows = db.execute("SELECT u.id,u.display_name,u.username,u.photo FROM actions a JOIN users u ON u.id=a.user_id WHERE a.post_id=? AND a.kind='like'", (post_id,)).fetchall()
            return [dict(id=row['id'], displayName=row['display_name'], handle=row['username'], photo=row['photo']) for row in rows]

    def connections(self,viewer_id,target_id,kind):
        if kind not in ('following','followers'):
            raise APIError(400,'Lista de pessoas inválida.')
        with self.connect() as db:
            person=db.execute('SELECT is_private FROM users WHERE id=?',(target_id,)).fetchone()
            if not person:raise APIError(404,'Esse perfil não foi encontrado.')
            own=viewer_id==target_id
            if not own and (person['is_private'] or not db.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(viewer_id,target_id)).fetchone()):
                raise APIError(403,'As conexões estão disponíveis nos perfis públicos que você segue.')
            joined,filtered=('target_id','user_id') if kind=='following' else ('user_id','target_id')
            access='' if own else ' AND (u.is_private=0 OR u.id=? OR EXISTS(SELECT 1 FROM follows allowed WHERE allowed.user_id=? AND allowed.target_id=u.id))'
            params=(target_id,) if own else (target_id,viewer_id,viewer_id)
            rows=db.execute(f'SELECT u.id,u.display_name,u.username,u.photo FROM users u JOIN follows f ON f.{joined}=u.id WHERE f.{filtered}=?{access} ORDER BY lower(u.display_name),u.id',params).fetchall()
            return [self.person(row) for row in rows]

    def interactions(self, user_id, post_id):
        with self.connect() as db:
            post = self.accessible(db, user_id, post_id)
            if post['owner_id'] != user_id:
                raise APIError(403, 'Só o autor pode ver as interações.')
            rows = db.execute("""SELECT u.id,u.display_name,u.username,u.photo,a.kind
                FROM actions a JOIN users u ON u.id=a.user_id
                WHERE a.post_id=? AND a.kind IN ('like','repost')
                AND (a.kind='like' OR u.is_private=0 OR u.id=? OR EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=u.id))
                ORDER BY lower(u.display_name),u.id,a.kind""", (post_id,user_id,user_id)).fetchall()
            people = {}
            for row in rows:
                person = people.setdefault(row['id'],dict(id=row['id'],displayName=row['display_name'],handle=row['username'],photo=row['photo'],liked=False,reposted=False))
                person['liked' if row['kind']=='like' else 'reposted'] = True
            return list(people.values())

    def preference(self, user_id, data):
        key, value = data.get('key'), data.get('value')
        if key == 'draft':
            if not isinstance(value, dict):
                raise APIError(400, 'Rascunho inválido.')
            message = value.get('text', '')
            if not isinstance(message, str) or len(message) > 2400:
                raise APIError(400, 'Rascunho muito longo.')
            with self.transaction() as db:
                track = clean_track(value['track']) if value.get('track') else None
                if track:
                    self.store_track(db, track)
                clean = dict(text=message, track=track, visibility='public' if value.get('visibility') == 'public' else 'private',lyricExcerpt=self.clean_excerpt(value.get('lyricExcerpt','')))
                db.execute('UPDATE users SET draft=? WHERE id=?', (json.dumps(clean), user_id))
        elif key == 'seen':
            clean = self.clean_seen(value)
            with self.transaction() as db:
                db.execute('UPDATE users SET seen=? WHERE id=?', (json.dumps(clean), user_id))
        else:
            raise APIError(400, 'Preferência inválida.')

    def import_legacy(self, user_id, data):
        items = data.get('entries', [])
        if not isinstance(items, list) or len(items) > 3000:
            raise APIError(400, 'Importação inválida.')
        with self.transaction() as db:
            user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if user['imported_at']:
                raise APIError(409, 'Este diário local já foi importado para esta conta.')
            mapping = {}
            for item in items:
                track_id = self.store_track(db, item.get('track'))
                identifier = str(uuid.uuid4())
                mapping[str(item.get('id', ''))] = identifier
                created = now_iso()
                try:
                    parsed = datetime.fromisoformat(item.get('createdAt', ''))
                    if parsed.tzinfo and parsed <= datetime.now(timezone.utc):
                        created = parsed.isoformat()
                except (ValueError, TypeError):
                    pass
                db.execute("INSERT INTO posts (id,owner_id,track_id,text,visibility,kind,created_at,updated_at) VALUES (?,?,?,?,?,'entry',?,?)", (identifier, user_id, track_id, text(item.get('text',''), 0, 2400), 'public' if item.get('visibility') == 'public' else 'private', created, created))
            for old_id in data.get('saved', []) if isinstance(data.get('saved'), list) else []:
                if isinstance(old_id, str) and old_id in mapping:
                    db.execute("INSERT INTO actions VALUES (?,?,'saved') ON CONFLICT DO NOTHING", (user_id, mapping[old_id]))
            previous_weekly = data.get('weekly')
            if isinstance(previous_weekly, dict) and previous_weekly.get('weekKey') == current_week() and not db.execute('SELECT 1 FROM weekly WHERE user_id=? AND week_key=?', (user_id,current_week())).fetchone():
                item = previous_weekly.get('item')
                identifier = None
                if item and not previous_weekly.get('deletedAt'):
                    identifier = str(uuid.uuid4())
                    track_id = self.store_track(db,item.get('track'))
                    db.execute("INSERT INTO posts (id,owner_id,track_id,text,visibility,kind,created_at,updated_at) VALUES (?,?,?,?,'public','weekly',?,?)", (identifier,user_id,track_id,text(item.get('text',''),0,2400),now_iso(),now_iso()))
                db.execute('INSERT INTO weekly VALUES (?,?,?,?,?)',(user_id,current_week(),identifier,now_iso(),now_iso() if not identifier else None))
            previous_profile = data.get('profile')
            # Import visual preferences only into a profile that has not been edited yet.
            if isinstance(previous_profile,dict) and user['profile_version'] == 0:
                favorites = previous_profile.get('favorites',[])
                favorites = [self.store_track(db,item) for item in favorites[:6]] if isinstance(favorites,list) else []
                background = self.store_track(db,previous_profile['background']) if previous_profile.get('background') else None
                old_pins=previous_profile.get('pinned',[])
                old_pins=[old_pins] if isinstance(old_pins,str) else old_pins
                pinned=[mapping[key] for key in old_pins if isinstance(key,str) and key in mapping and any(item.get('id')==key and item.get('visibility')=='public' for item in items)] if isinstance(old_pins,list) else []
                photo=previous_profile.get('photo','')
                photo=photo if isinstance(photo,str) and len(photo)<=200000 and re.fullmatch(r'data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+',photo) else ''
                db.execute('UPDATE users SET bio=?,photo=?,favorites=?,background=?,pinned=?,profile_version=profile_version+1 WHERE id=?', (text(previous_profile.get('bio',''),0,180),photo,json.dumps(favorites),background,json.dumps(pinned),user_id))
            draft=data.get('draft')
            if isinstance(draft,dict) and draft.get('text') and not json.loads(user['draft']).get('text'):
                message=text(draft['text'],0,2400)
                track=clean_track(draft['track']) if draft.get('track') else None
                db.execute('UPDATE users SET draft=? WHERE id=?',(json.dumps(dict(text=message,track=track,visibility='public' if draft.get('visibility')=='public' else 'private')),user_id))
            db.execute('UPDATE users SET imported_at=?,entries_version=entries_version+1 WHERE id=?', (now_iso(), user_id))
        return len(items)
