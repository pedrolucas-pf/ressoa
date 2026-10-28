"""Account/API integration tests with real SQLite and disposable accounts."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from webapp import Application
from database import APIError, current_week
from scripts.backup import backup
from scripts.verification_support import verification_source

TRACK = dict(catalogId='spotify:6jVWIRz01vnJ1VE8LtWK6Q', provider='spotify', title='Clube da Esquina Nº 2', artist='Milton Nascimento & Lô Borges', album='Clube da Esquina', artwork='https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e020f18b9691fefc38827ffbd7a', duration=218)


class Accounts(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = Application(verification_source(Path(self.directory.name) / 'test.sqlite3'), production=False)
        self.cookies = {}

    def tearDown(self):
        self.directory.cleanup()

    def call(self, path, method='GET', data=None, actor='a', origin='http://test.local'):
        raw = json.dumps(data if data is not None else {}).encode()
        route, _, query = path.partition('?')
        env = dict(REQUEST_METHOD=method, PATH_INFO=route, QUERY_STRING=query, HTTP_HOST='test.local',
                   HTTP_ORIGIN=origin, HTTP_X_RESSOA_CLIENT='web', CONTENT_TYPE='application/json', CONTENT_LENGTH=str(len(raw)), REMOTE_ADDR='127.0.0.1', HTTP_COOKIE=self.cookies.get(actor, ''), **{'wsgi.input': io.BytesIO(raw), 'wsgi.url_scheme': 'http'})
        result = {}
        def start(status, headers):
            result['status'], result['headers'] = int(status.split()[0]), dict(headers)
        payload = b''.join(self.app(env, start))
        if 'Set-Cookie' in result['headers']:
            self.cookies[actor] = result['headers']['Set-Cookie'].split(';')[0]
        result['data'] = json.loads(payload) if result['headers'].get('Content-Type', '').startswith('application/json') else None
        return result

    def register(self, actor='a', remember=True):
        result = self.call('/api/register', 'POST', dict(email=f'{actor}@example.com', username=f'user_{actor}', displayName=f'Pessoa {actor}', password='test-password-123', remember=remember), actor)
        self.assertEqual(result['status'], 200, result)
        return result['data']

    def save(self, items, version=0, actor='a'):
        return self.call('/api/entries', 'PUT', {'value': items, 'version': version}, actor)

    def test_accounts_sessions_and_restart(self):
        state = self.register()
        cookie = self.cookies['a']
        self.assertIn('HttpOnly', self.call('/api/login', 'POST', {'identifier': 'A@EXAMPLE.COM', 'password': 'test-password-123', 'remember': True})['headers']['Set-Cookie'])
        self.assertIn('Max-Age=2592000', self.call('/api/login', 'POST', {'identifier': '@user_a', 'password': 'test-password-123', 'remember': True})['headers']['Set-Cookie'])
        result = self.call('/api/login', 'POST', {'identifier': 'user_a', 'password': 'test-password-123', 'remember': False})
        self.assertNotIn('Max-Age', result['headers']['Set-Cookie'])
        self.assertEqual(self.call('/api/login', 'POST', {'identifier': 'user_a', 'password': 'bad-password'})['status'], 401)
        self.app = Application(self.app.db.source, production=False)
        self.assertEqual(self.call('/api/bootstrap')['data']['user']['id'], state['user']['id'])
        with self.app.db.connect() as db:
            self.assertNotIn('test-password-123', db.execute('SELECT password_hash FROM users').fetchone()[0])
            self.assertNotEqual(db.execute('SELECT token_hash FROM sessions LIMIT 1').fetchone()[0], cookie.split('=')[1])
        self.call('/api/logout', 'POST', {})
        self.assertEqual(self.call('/api/bootstrap')['status'], 401)
        self.assertEqual(self.call('/api/session')['data'], {'authenticated': False})

    def test_ownership_visibility_social_and_conflicts(self):
        a = self.register('a'); self.register('b')
        public = dict(id='first-post', track=TRACK, text='Uma lembrança guardada nesta música.', visibility='public', ownerId='forged-owner')
        private = dict(public, id='private-post', visibility='private', text='Uma lembrança que continua privada.')
        result = self.save([public, private]); self.assertEqual(result['status'], 200)
        self.assertEqual(result['data']['entries'][0]['ownerId'], a['user']['id'])
        b = self.call('/api/bootstrap', actor='b')['data']
        self.assertEqual([p['id'] for p in b['publicPosts']], ['first-post'])
        self.assertEqual(self.save([dict(public, text='Tentativa de substituir texto alheio.')], actor='b')['status'], 403)
        for kind in ('like', 'repost', 'saved'):
            self.assertEqual(self.call('/api/action', 'POST', dict(kind=kind, target='first-post', active=True), 'b')['status'], 200)
            self.assertEqual(self.call('/api/action', 'POST', dict(kind=kind, target='private-post', active=True), 'b')['status'], 404)
        self.assertEqual(self.call('/api/action', 'POST', dict(kind='follow', target=a['user']['id'], active=True), 'b')['status'], 200)
        people = self.call('/api/likes?post=first-post')['data']['people']
        self.assertEqual(people[0]['handle'], 'user_b')
        self.assertEqual(self.call('/api/likes?post=first-post', actor='b')['status'], 403)
        self.assertNotIn('likeCount', self.call('/api/bootstrap', actor='b')['data']['publicPosts'][0])
        self.assertEqual(self.save([public], version=0)['status'], 409)
        self.assertEqual(self.save([dict(public, visibility='private'), private], version=1)['status'], 200)
        b = self.call('/api/bootstrap', actor='b')['data']
        self.assertEqual(b['publicPosts'], []); self.assertEqual(b['saved'], []); self.assertEqual(b['social']['reposts'], [])

    def test_weekly_atomic_lock_and_independent_text(self):
        self.register()
        post = dict(id='journal-entry', track=TRACK, text='O comentário que permanece no meu diário.', visibility='public')
        self.save([post])
        result = self.call('/api/weekly', 'POST', dict(track=TRACK, text='Outra mensagem para a semana.', weekKey='2050-01-01'))
        self.assertEqual(result['status'], 200)
        state = result['data']; self.assertEqual(len(state['entries']), 1)
        self.assertNotEqual(state['weekly']['item']['text'], post['text'])
        self.assertEqual(state['weekly']['weekKey'], state['serverWeek'])
        self.assertEqual(self.call('/api/weekly', 'POST', dict(track=TRACK, text='Uma segunda tentativa inválida.'))['status'], 409)
        state = self.call('/api/weekly', 'DELETE', {})['data']
        self.assertIsNone(state['weekly']['item']); self.assertTrue(state['weekly']['deletedAt'])
        self.assertEqual(self.call('/api/weekly', 'POST', dict(track=TRACK, text='Não pode repor após apagar.'))['status'], 409)
        self.app = Application(self.app.db.source, production=False)
        self.assertTrue(self.call('/api/bootstrap')['data']['weekly']['deletedAt'])

    def test_profile_and_import_survive_restart(self):
        state = self.register()
        profile = dict(state['profile'], displayName='Novo nome', bio='Meu diário musical', favorites=[TRACK], background=TRACK)
        self.assertEqual(self.call('/api/profile', 'PUT', dict(value=profile, version=0))['status'], 200)
        legacy = dict(entries=[dict(track=TRACK, text='Comentário que já existia no navegador.', visibility='private')])
        self.assertEqual(self.call('/api/import', 'POST', legacy)['status'], 200)
        self.assertEqual(self.call('/api/import', 'POST', legacy)['status'], 409)
        self.app = Application(self.app.db.source, production=False)
        state = self.call('/api/bootstrap')['data']
        self.assertEqual(state['profile']['background']['catalogId'], TRACK['catalogId'])
        self.assertEqual(len(state['entries']), 1); self.assertEqual(state['entries'][0]['visibility'], 'private')

    def test_complete_legacy_import_and_consistent_backup(self):
        self.register()
        old = dict(id='old-id', track=TRACK, text='Uma ressoa pública antiga que deve ser preservada.', visibility='public', createdAt='2026-01-01T18:00:00+00:00')
        data = dict(entries=[old], saved=['old-id'], profile=dict(bio='Minha bio antiga', photo='', favorites=[TRACK], background=TRACK, pinned='old-id'),
                    weekly=dict(weekKey=current_week(), item=dict(old, text='Outro comentário no destaque antigo.')),
                    draft=dict(text='Um rascunho ainda não publicado.',track=TRACK,visibility='private'))
        result = self.call('/api/import','POST',data)
        self.assertEqual(result['status'],200,result)
        state=result['data']; new_id=state['entries'][0]['id']
        self.assertEqual(state['profile']['pinned'],[new_id]);self.assertEqual(state['saved'],[new_id])
        self.assertEqual(state['entries'][0]['createdAt'],old['createdAt'])
        self.assertEqual(state['profile']['handle'],'user_a');self.assertEqual(state['draft']['text'],data['draft']['text'])
        self.assertNotEqual(state['weekly']['item']['text'],state['entries'][0]['text'])
        if not self.app.db.is_postgres:
            copied=backup(self.app.db.path,Path(self.directory.name)/'snapshot.sqlite3')
            restored=Application(copied,production=False)
            self.assertEqual(restored.db.bootstrap(state['user']['id'])['entries'][0]['text'],old['text'])

    def test_concurrent_weekly_selection_is_one_choice(self):
        state=self.register();user=state['user']['id']
        def choose(_):
            try:
                self.app.db.choose_weekly(user,dict(track=TRACK,text='Uma escolha concorrente para esta semana.'))
                return 200
            except APIError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(choose,range(2))),[200,409])

    def test_session_expiry_uniqueness_and_rate_limit(self):
        self.register()
        result=self.call('/api/register','POST',dict(email='A@EXAMPLE.COM',username='different',displayName='Outra pessoa',password='test-password-123'))
        self.assertEqual(result['status'],409)
        with self.app.db.transaction() as db:
            db.execute('UPDATE sessions SET expires_at=0')
        self.assertEqual(self.call('/api/bootstrap')['status'],401)
        for i in range(16):
            result=self.call('/api/login','POST',dict(identifier='missing-user',password='wrong-password'))
        self.assertEqual(result['status'],429)

    def test_request_protection_and_static_files(self):
        self.assertEqual(self.call('/api/bootstrap')['status'], 401)
        self.assertEqual(self.call('/api/register', 'POST', {}, origin='https://other.example')['status'], 403)
        for path in ['/storage/ressoa.sqlite3', '/database.py', '/.env', '/.tools/', '/assets/../database.py', '/README.md']:
            self.assertEqual(self.call(path)['status'], 404, path)
        self.assertEqual(self.call('/')['status'], 200)
        self.assertEqual(self.call('/auth.js')['status'], 200)
        with patch.dict(os.environ, {'APP_ORIGIN': 'https://ressoa.example'}):
            production = Application(self.app.db.source, production=True)
            self.assertIn('Secure', production.cookie('test')[0][1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
