"""Optional Spotify authorization and playback. Refresh tokens stay server-side."""
import base64
import hashlib
import json
import math
import os
import re
import secrets
import time
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from database import APIError,clean_track,text


class SpotifyHTTPError(Exception):
    def __init__(self,status):self.status=status


def spotify_request(path,token=None,method='GET',data=None,form=False):
    url='https://accounts.spotify.com/api/token' if form else 'https://api.spotify.com/v1/'+path
    headers={'Accept':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    body=None
    if data is not None:
        headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
        body=(urlencode(data) if form else json.dumps(data)).encode()
    try:
        with urlopen(Request(url,headers=headers,data=body,method=method),timeout=15) as response:
            raw=response.read(2_000_000)
            return json.loads(raw) if raw else {}
    except HTTPError as error:raise SpotifyHTTPError(error.code) from None
    except (OSError,ValueError):raise APIError(503,'O Spotify não respondeu. Tente novamente.') from None


def spotify_track(item):
    album=item.get('album') or {};identifier=item.get('id','')
    if not re.fullmatch(r'[A-Za-z0-9]{22}',identifier):raise APIError(400,'Faixa inválida no Spotify.')
    images=album.get('images') or []
    return clean_track(dict(catalogId='spotify:'+identifier,title=item.get('name',''),
        artist=', '.join(artist.get('name','') for artist in item.get('artists',[])),album=album.get('name',''),
        duration=(item.get('duration_ms') or 0)/1000,year=str(album.get('release_date',''))[:4],
        releaseDate=album.get('release_date',''),artwork=images[0].get('url','') if images else '',
        isrc=(item.get('external_ids') or {}).get('isrc',''),explicit=item.get('explicit')))


class Spotify:
    def __init__(self,database):
        self.db=database;self.client_id=os.getenv('SPOTIFY_CLIENT_ID','').strip();self.lock=Lock()

    @property
    def configured(self):return bool(re.fullmatch(r'[A-Za-z0-9]{32}',self.client_id))

    def connection(self,user_id):
        if not self.configured:return None
        with self.db.connect() as db:
            return db.execute('SELECT * FROM spotify_connections WHERE user_id=? AND client_id=?',(user_id,self.client_id)).fetchone()

    def status(self,user_id):
        row=self.connection(user_id)
        return dict(configured=self.configured,connected=bool(row),displayName=row['display_name'] if row else '')

    def begin(self,user_id,session,redirect_uri):
        if not self.configured:raise APIError(503,'A conexão com Spotify ainda não foi configurada.')
        state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self.db.transaction() as db:
            db.execute('DELETE FROM spotify_oauth WHERE user_id=? OR expires_at<?',(user_id,time.time()))
            db.execute('INSERT INTO spotify_oauth VALUES (?,?,?,?,?,?)',(hashlib.sha256(state.encode()).hexdigest(),user_id,hashlib.sha256(session.encode()).hexdigest(),verifier,redirect_uri,time.time()+600))
        scope='streaming user-read-private user-read-email user-modify-playback-state user-read-playback-state'
        return dict(url='https://accounts.spotify.com/authorize?'+urlencode(dict(client_id=self.client_id,response_type='code',redirect_uri=redirect_uri,state=state,scope=scope,code_challenge_method='S256',code_challenge=challenge)))

    def finish(self,user_id,session,state,code,error=''):
        if not self.configured or not user_id or not isinstance(state,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',state):
            raise APIError(400,'Essa conexão expirou. Volte ao Ressoa e tente novamente.')
        with self.db.transaction() as db:
            row=db.execute('''DELETE FROM spotify_oauth WHERE state_hash=? AND user_id=? AND session_hash=? AND expires_at>? RETURNING verifier,redirect_uri''',
                (hashlib.sha256(state.encode()).hexdigest(),user_id,hashlib.sha256(session.encode()).hexdigest(),time.time())).fetchone()
        if not row:raise APIError(400,'Essa conexão expirou. Volte ao Ressoa e tente novamente.')
        if error:raise APIError(400,'A conexão com Spotify foi cancelada.')
        code=text(code,1,2000)
        try:
            tokens=spotify_request('',method='POST',form=True,data=dict(grant_type='authorization_code',code=code,redirect_uri=row['redirect_uri'],client_id=self.client_id,code_verifier=row['verifier']))
            access,refresh,expires=self.validate_tokens(tokens)
            profile=spotify_request('me',access)
        except SpotifyHTTPError:
            raise APIError(503,'O Spotify recusou a conexão. Confira o aplicativo e os usuários autorizados no painel.') from None
        if not isinstance(profile,dict):raise APIError(503,'Não foi possível conferir a conta do Spotify.')
        if profile.get('product') and profile['product']!='premium':raise APIError(403,'A reprodução completa exige uma conta Spotify Premium.')
        identifier=str(profile.get('id') or profile.get('account_id') or '')[:200]
        if not identifier:raise APIError(503,'Não foi possível identificar a conta do Spotify.')
        with self.db.transaction() as db:
            if not db.execute('SELECT 1 FROM sessions WHERE token_hash=? AND user_id=? AND expires_at>?',(hashlib.sha256(session.encode()).hexdigest(),user_id,time.time())).fetchone():
                raise APIError(400,'Sua sessão mudou. Entre novamente no Ressoa para conectar o Spotify.')
            db.execute('''INSERT INTO spotify_connections VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                client_id=excluded.client_id,spotify_user_id=excluded.spotify_user_id,display_name=excluded.display_name,
                access_token=excluded.access_token,refresh_token=excluded.refresh_token,expires_at=excluded.expires_at''',
                (user_id,self.client_id,identifier,str(profile.get('display_name') or 'Spotify')[:100],access,refresh,expires))

    @staticmethod
    def validate_tokens(data,refresh=''):
        if not isinstance(data,dict):raise APIError(503,'O Spotify não devolveu uma autorização válida.')
        access=data.get('access_token');refresh=data.get('refresh_token') or refresh;expires=data.get('expires_in')
        if not isinstance(access,str) or not 1<=len(access)<=10000 or not isinstance(refresh,str) or not 1<=len(refresh)<=10000 or type(expires) not in (int,float) or not math.isfinite(expires) or not 30<=expires<=86400:
            raise APIError(503,'O Spotify não devolveu uma autorização válida.')
        return access,refresh,time.time()+expires

    def token(self,user_id):
        row=self.connection(user_id)
        if not row:raise APIError(403,'Conecte sua conta Spotify Premium para usar esta função.')
        if row['expires_at']>time.time()+60:return row['access_token']
        with self.lock:
            row=self.connection(user_id)
            if not row:raise APIError(403,'Reconecte sua conta do Spotify.')
            if row['expires_at']>time.time()+60:return row['access_token']
            try:
                data=spotify_request('',method='POST',form=True,data=dict(grant_type='refresh_token',refresh_token=row['refresh_token'],client_id=self.client_id))
                access,refresh,expires=self.validate_tokens(data,row['refresh_token'])
            except SpotifyHTTPError:raise APIError(403,'Sua autorização do Spotify expirou. Conecte novamente.') from None
            with self.db.transaction() as db:
                changed=db.execute('''UPDATE spotify_connections SET access_token=?,refresh_token=?,expires_at=?
                    WHERE user_id=? AND client_id=? AND refresh_token=? RETURNING user_id''',(access,refresh,expires,user_id,self.client_id,row['refresh_token'])).fetchone()
            if not changed:raise APIError(409,'A conexão com Spotify mudou. Tente novamente.')
            return access

    def request(self,user_id,path,method='GET',data=None):
        try:return spotify_request(path,self.token(user_id),method,data)
        except SpotifyHTTPError as error:
            if error.status==401:raise APIError(403,'Reconecte sua conta do Spotify.') from None
            if error.status==429:raise APIError(429,'O Spotify está limitando as consultas. Aguarde um pouco.') from None
            raise APIError(503,'O Spotify não conseguiu concluir. Confira sua conta Premium e a autorização do aplicativo.') from None

    def search(self,user_id,query,offset=0):
        query=text(query,2,180)
        if not 0<=offset<=1000:raise APIError(400,'Página de busca inválida.')
        data=self.request(user_id,'search?'+urlencode(dict(q=query,type='track',limit=10,offset=offset)))
        result=data.get('tracks') or {};items=[]
        for track in result.get('items') or []:
            if track and not track.get('is_local') and track.get('is_playable') is not False:
                items.append(spotify_track(track))
        return dict(results=items,provider='spotify',nextOffset=offset+10 if result.get('next') and offset<1000 else None)

    def track(self,user_id,identifier):
        if not re.fullmatch(r'[A-Za-z0-9]{22}',identifier):raise APIError(400,'Faixa inválida.')
        return spotify_track(self.request(user_id,'tracks/'+identifier))

    def play(self,user_id,data):
        identifier=text(data.get('trackId'),1,22);device=text(data.get('deviceId'),1,128);start=data.get('start',0)
        if not re.fullmatch(r'[A-Za-z0-9]{22}',identifier) or not re.fullmatch(r'[A-Za-z0-9_-]+',device) or type(start) not in (int,float) or not math.isfinite(start) or not 0<=start<=86400:
            raise APIError(400,'Trecho ou dispositivo inválido.')
        self.request(user_id,'me/player/play?'+urlencode(dict(device_id=device)),method='PUT',data=dict(uris=['spotify:track:'+identifier],position_ms=round(start*1000)))
        return dict(ok=True)

    def disconnect(self,user_id):
        with self.db.transaction() as db:
            db.execute('DELETE FROM spotify_oauth WHERE user_id=?',(user_id,))
            db.execute('DELETE FROM spotify_connections WHERE user_id=?',(user_id,))
        return dict(ok=True)
