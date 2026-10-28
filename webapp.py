"""WSGI application shared by the local runner and the production server."""
import json
import logging
import mimetypes
import os
from time import perf_counter
from contextlib import nullcontext
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, unquote
from database import APIError, Database
from services import ServiceError, search_tracks, get_track, lyrics, login_artwork

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / 'web'
MAX_BODY = 12_000_000


class Application:
    def __init__(self, database_path=None, production=None):
        self.production = (os.getenv('RESSOA_ENV') == 'production') if production is None else production
        self.origin = os.getenv('APP_ORIGIN', '').rstrip('/')
        if not self.origin and os.getenv('RENDER_EXTERNAL_HOSTNAME'):
            self.origin = 'https://' + os.environ['RENDER_EXTERNAL_HOSTNAME']
        if self.production and not self.origin.startswith('https://'):
            raise RuntimeError('Defina APP_ORIGIN com o endereço HTTPS público do Ressoa.')
        if database_path is None and os.getenv('DATABASE_URL') and not os.environ['DATABASE_URL'].startswith(('postgres://','postgresql://')):
            raise RuntimeError('DATABASE_URL precisa ser uma conexão PostgreSQL válida.')
        if self.production and database_path is None and not os.getenv('DATABASE_URL'):
            raise RuntimeError('Defina DATABASE_URL do Neon antes de publicar.')
        source=database_path if database_path is not None else os.getenv('DATABASE_URL') or os.getenv('DATABASE_PATH') or str(ROOT/'storage'/'ressoa.sqlite3')
        self.db=Database(source)

    def __call__(self, env, start_response):
        started = perf_counter()
        headers = [('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'strict-origin-when-cross-origin'),
                   ('X-Frame-Options', 'DENY'), ('Cache-Control', 'no-store')]
        if self.production:
            headers.append(('Strict-Transport-Security', 'max-age=31536000'))
        try:
            scope = self.db.request_scope() if env.get('PATH_INFO', '').startswith('/api/') else nullcontext()
            with scope:
                status, body, extra = self.dispatch(env)
            headers.extend(extra)
        except APIError as error:
            status, body = error.status, dict(error=error.message)
        except (ValueError, TypeError, KeyError, AttributeError):
            status, body = 400, dict(error='Dados inválidos. Confira os campos e tente novamente.')
        except ServiceError as error:
            status, body = 503, dict(error=str(error))
        except Exception:
            logging.exception('Request failed: %s %s', env.get('REQUEST_METHOD'), env.get('PATH_INFO'))
            status, body = 500, dict(error='Não foi possível salvar ou carregar os dados. Tente novamente.')
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
            headers.append(('Content-Type', 'application/json; charset=utf-8'))
        headers.append(('Content-Length', str(len(body))))
        headers.append(('Server-Timing', f'app;dur={(perf_counter()-started)*1000:.1f}'))
        start_response(f'{status} {HTTPStatus(status).phrase}', headers)
        return [] if env.get('REQUEST_METHOD') == 'HEAD' else [body]

    def cookie(self, token, remember=False, clear=False):
        value = f'ressoa_session={token}; Path=/; HttpOnly; SameSite=Lax'
        if self.production:
            value += '; Secure'
        if clear:
            value += '; Max-Age=0'
        elif remember:
            value += '; Max-Age=2592000'
        return [('Set-Cookie', value)]

    @staticmethod
    def token(env):
        cookie = SimpleCookie()
        try:
            cookie.load(env.get('HTTP_COOKIE', ''))
            return cookie['ressoa_session'].value if 'ressoa_session' in cookie else ''
        except Exception:
            return ''

    def body(self, env):
        origin = self.origin or f"{env.get('wsgi.url_scheme', 'http')}://{env.get('HTTP_HOST', '')}"
        if env.get('HTTP_ORIGIN') != origin or env.get('HTTP_X_RESSOA_CLIENT') != 'web':
            raise APIError(403, 'Requisição de origem não permitida. Reabra o Ressoa e tente novamente.')
        if env.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
            raise APIError(415, 'Use o formulário do Ressoa.')
        length = int(env.get('CONTENT_LENGTH') or 0)
        if length <= 0 or length > MAX_BODY:
            raise APIError(413, 'Os dados enviados são muito grandes.')
        try:
            data = json.loads(env['wsgi.input'].read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError):
            raise APIError(400, 'Dados inválidos.')
        if not isinstance(data, dict):
            raise APIError(400, 'Dados inválidos.')
        return data

    def dispatch(self, env):
        path, method = env.get('PATH_INFO', '/'), env['REQUEST_METHOD']
        if path in ('/healthz', '/readyz') and method in ('GET', 'HEAD'):
            # Frequent liveness checks must not keep the Neon compute awake.
            if path == '/readyz':
                with self.db.connect() as db:
                    db.execute('SELECT 1').fetchone()
            return 200, {'ok': True}, []
        if not path.startswith('/api/'):
            if method not in ('GET', 'HEAD'):
                raise APIError(405, 'Método não permitido.')
            path = unquote(path)
            public = {'/', '/index.html', '/styles.css'} | {f'/{file.name}' for file in WEB_ROOT.glob('*.js')}
            if '..' in path.split('/') or '\\' in path or not (path in public or path.startswith('/assets/')):
                raise APIError(404, 'Página não encontrada.')
            file = (WEB_ROOT / ('index.html' if path == '/' else path.lstrip('/'))).resolve()
            if not file.is_relative_to(WEB_ROOT) or not file.is_file():
                raise APIError(404, 'Página não encontrada.')
            mime = 'text/javascript' if file.suffix == '.js' else mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            return 200, file.read_bytes(), [('Content-Type', mime)]
        token = self.token(env)
        user_id = self.db.session_user(token) if token else None
        data = self.body(env) if method in ('POST', 'PUT', 'DELETE') else {}
        if path in ('/api/register', '/api/login') and method == 'POST':
            self.db.limit('auth-ip:' + env.get('REMOTE_ADDR', ''), 100)
            if path == '/api/register':
                self.db.limit('register-ip:' + env.get('REMOTE_ADDR', ''), 15, 3600)
                user_id = self.db.register(data)
            else:
                user_id = self.db.login(data)
            if token:
                self.db.logout(token)
            remember = data.get('remember') is True
            token = self.db.create_session(user_id, remember)
            return 200, self.db.bootstrap(user_id), self.cookie(token, remember)
        if path == '/api/session' and method == 'GET':
            return 200, {'authenticated': bool(user_id)}, []
        if path == '/api/login-artwork' and method == 'GET':
            self.db.limit('artwork:' + env.get('REMOTE_ADDR', ''), 60, 60)
            return 200, login_artwork(), []
        if path == '/api/logout' and method == 'POST':
            self.db.logout(token)
            return 200, {'ok': True}, self.cookie('', clear=True)
        if not user_id:
            raise APIError(401, 'Entre na sua conta para continuar.')
        params = parse_qs(env.get('QUERY_STRING', ''))
        value = lambda key, default='': params.get(key, [default])[0]
        if path == '/api/bootstrap' and method == 'GET':
            return 200, self.db.bootstrap(user_id), []
        if path == '/api/post' and method == 'GET':
            self.db.limit('post-read:'+user_id,90,60)
            return 200, {'post':self.db.shared_post(user_id,value('id'))}, []
        if path == '/api/people' and method == 'GET':
            self.db.limit('people-search:'+user_id,90,60)
            return 200, {'people':self.db.search_people(user_id,value('q'))}, []
        if path == '/api/profile' and method == 'GET':
            self.db.limit('profile-read:'+user_id,90,60)
            return 200, self.db.public_profile(user_id,value('user'),int(value('offset','0')),int(value('repostOffset','0'))), []
        if method == 'GET' and path in ('/api/search', '/api/track', '/api/lyrics'):
            self.db.limit('music:' + user_id, 180, 60)
            if path == '/api/search':
                payload = search_tracks(value('q'))
            elif path == '/api/track':
                payload = get_track(value('id'))
                self.db.cache_verified_track(payload)
            else:
                payload = lyrics(value('title'), value('artist'), value('album'), value('duration', '0'))
            return 200, payload, []
        if path == '/api/likes' and method == 'GET':
            return 200, {'people': self.db.likes(user_id, value('post'))}, []
        if path == '/api/interactions' and method == 'GET':
            self.db.limit('interaction-read:'+user_id,90,60)
            return 200, {'people': self.db.interactions(user_id, value('post'))}, []
        if path == '/api/connections' and method == 'GET':
            self.db.limit('connections-read:'+user_id,90,60)
            return 200, {'people':self.db.connections(user_id,value('user'),value('kind'))}, []
        if path == '/api/follow-requests' and method == 'GET':
            self.db.limit('requests-read:'+user_id,90,60)
            return 200, {'people':self.db.requests_for(user_id)}, []
        if method in ('PUT', 'POST', 'DELETE'):
            self.db.limit('write:' + user_id, 180, 60)
            if path == '/api/entries' and method == 'PUT':
                self.db.save_entries(user_id, data)
            elif path == '/api/profile' and method == 'PUT':
                self.db.save_profile(user_id, data)
            elif path == '/api/weekly' and method == 'POST':
                self.db.choose_weekly(user_id, data)
            elif path == '/api/weekly' and method == 'DELETE':
                self.db.delete_weekly(user_id)
            elif path == '/api/action' and method == 'POST':
                result = self.db.action(user_id, data.get('kind'), data.get('target'), data.get('active'))
                if data.get('compact') is True and result is not None:
                    return 200, result, []
            elif path == '/api/follow-request' and method == 'POST':
                self.db.respond_follow(user_id,data)
            elif path == '/api/follower' and method == 'DELETE':
                self.db.remove_follower(user_id,data)
            elif path == '/api/preference' and method == 'PUT':
                self.db.preference(user_id, data)
                return 200, {'ok': True}, []
            elif path == '/api/import' and method == 'POST':
                self.db.import_legacy(user_id, data)
            else:
                raise APIError(404, 'Operação não encontrada.')
            return 200, self.db.bootstrap(user_id), []
        raise APIError(404, 'Página não encontrada.')


def create_app():
    return Application()
