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
    def __init__(self,status,reason=''):self.status,self.reason=status,reason


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
    except HTTPError as error:
        reason=''
        try:
            payload=json.loads(error.read(16000));detail=payload.get('error')
            if isinstance(detail,dict):
                reason=detail.get('reason','');message=str(detail.get('message','')).lower()
                if not reason:
                    for phrase,value in (('premium required','PREMIUM_REQUIRED'),('no active device','NO_ACTIVE_DEVICE'),('device not found','DEVICE_NOT_FOUND'),('insufficient client scope','INSUFFICIENT_SCOPE')):
                        if phrase in message:reason=value;break
            elif detail=='invalid_grant':reason='invalid_grant'
            if reason not in ('PREMIUM_REQUIRED','NO_ACTIVE_DEVICE','DEVICE_NOT_FOUND','INSUFFICIENT_SCOPE','RESTRICTION_VIOLATED','TRACK_NOT_PLAYABLE','invalid_grant'):reason=''
        except (OSError,ValueError,TypeError,AttributeError):pass
        finally:error.close()
        raise SpotifyHTTPError(error.code,reason) from None
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
        if not user_id or not session:raise APIError(400,'Sua sessão Ressoa não está disponível nesta aba. Abra o Ressoa no mesmo navegador, entre na conta e conecte o Spotify por lá.','SPOTIFY_SESSION_REQUIRED')
        if not self.configured or not isinstance(state,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',state):
            raise APIError(400,'Essa conexão expirou. Volte ao Ressoa e tente novamente.')
        with self.db.transaction() as db:
            row=db.execute('''DELETE FROM spotify_oauth WHERE state_hash=? AND user_id=? AND session_hash=? AND expires_at>? RETURNING verifier,redirect_uri''',
                (hashlib.sha256(state.encode()).hexdigest(),user_id,hashlib.sha256(session.encode()).hexdigest(),time.time())).fetchone()
        if not row:raise APIError(400,'Essa conexão expirou. Volte ao Ressoa e tente novamente.')
        if error:raise APIError(400,'A conexão com Spotify foi cancelada.','SPOTIFY_AUTH_CANCELLED')
        code=text(code,1,2000)
        try:
            tokens=spotify_request('',method='POST',form=True,data=dict(grant_type='authorization_code',code=code,redirect_uri=row['redirect_uri'],client_id=self.client_id,code_verifier=row['verifier']))
            access,refresh,expires=self.validate_tokens(tokens)
        except SpotifyHTTPError as failure:
            if failure.reason=='invalid_grant':raise APIError(400,'Essa autorização do Spotify expirou. Volte ao Ressoa e conecte novamente.','SPOTIFY_AUTH_REQUIRED') from None
            if failure.status==429:raise APIError(429,'O Spotify está limitando as conexões. Aguarde um pouco e tente novamente.','SPOTIFY_RATE_LIMIT') from None
            raise APIError(503,'O Spotify recusou a autorização do aplicativo. Confira o Client ID e o endereço de retorno no painel.','SPOTIFY_CONFIGURATION_ERROR') from None
        try:profile=spotify_request('me',access)
        except SpotifyHTTPError as failure:
            if failure.status==403:
                raise APIError(403,'O Spotify recusou o acesso desta conta. Em modo de desenvolvimento, o responsável pelo Ressoa precisa adicionar o e-mail da sua conta Spotify em Settings → Users Management, no painel do aplicativo.','SPOTIFY_ACCESS_DENIED') from None
            if failure.status==429:raise APIError(429,'O Spotify está limitando as conexões. Aguarde um pouco e tente novamente.','SPOTIFY_RATE_LIMIT') from None
            raise APIError(503,'Não foi possível conferir sua conta no Spotify agora. Volte ao Ressoa e tente novamente.','SPOTIFY_UNAVAILABLE') from None
        if not isinstance(profile,dict):raise APIError(503,'Não foi possível conferir a conta do Spotify.')
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

    def expire_connection(self,user_id,access):
        # Do not remove a newer connection established while a request was in flight.
        with self.db.transaction() as db:
            db.execute('DELETE FROM spotify_connections WHERE user_id=? AND client_id=? AND access_token=?',(user_id,self.client_id,access))

    def token(self,user_id,rejected_token=None):
        row=self.connection(user_id)
        if not row:raise APIError(403,'Conecte sua conta Spotify para ouvir este trecho.','SPOTIFY_AUTH_REQUIRED')
        if row['expires_at']>time.time()+60 and row['access_token']!=rejected_token:return row['access_token']
        with self.lock:
            row=self.connection(user_id)
            if not row:raise APIError(403,'Conecte sua conta Spotify para ouvir este trecho.','SPOTIFY_AUTH_REQUIRED')
            if row['expires_at']>time.time()+60 and row['access_token']!=rejected_token:return row['access_token']
            try:
                data=spotify_request('',method='POST',form=True,data=dict(grant_type='refresh_token',refresh_token=row['refresh_token'],client_id=self.client_id))
                access,refresh,expires=self.validate_tokens(data,row['refresh_token'])
            except SpotifyHTTPError as error:
                if error.reason=='invalid_grant':
                    self.expire_connection(user_id,row['access_token'])
                    raise APIError(403,'A conexão com Spotify expirou. Use Conectar Spotify para autorizar novamente.','SPOTIFY_AUTH_REQUIRED') from None
                if error.status==429:raise APIError(429,'O Spotify está limitando as consultas. Aguarde um pouco.','SPOTIFY_RATE_LIMIT') from None
                raise APIError(503,'Não foi possível renovar o acesso ao Spotify agora. Tente novamente em instantes.','SPOTIFY_UNAVAILABLE') from None
            with self.db.transaction() as db:
                changed=db.execute('''UPDATE spotify_connections SET access_token=?,refresh_token=?,expires_at=?
                    WHERE user_id=? AND client_id=? AND refresh_token=? RETURNING user_id''',(access,refresh,expires,user_id,self.client_id,row['refresh_token'])).fetchone()
            if not changed:raise APIError(409,'A conexão com Spotify mudou. Tente novamente.')
            return access

    def request(self,user_id,path,method='GET',data=None):
        access=self.token(user_id)
        for attempt in range(2):
            try:return spotify_request(path,access,method,data)
            except SpotifyHTTPError as error:
                if error.status==401:
                    if not attempt:access=self.token(user_id,rejected_token=access);continue
                    self.expire_connection(user_id,access)
                    raise APIError(403,'A conexão com Spotify expirou. Use Conectar Spotify para autorizar novamente.','SPOTIFY_AUTH_REQUIRED') from None
                if error.status==429:raise APIError(429,'O Spotify está limitando as consultas. Aguarde um pouco.','SPOTIFY_RATE_LIMIT') from None
                if path.startswith('me/player/play') and (error.status==404 or error.reason in ('NO_ACTIVE_DEVICE','DEVICE_NOT_FOUND')):
                    raise APIError(409,'O player perdeu a conexão com Spotify. Toque no play para tentar novamente.','SPOTIFY_DEVICE_UNAVAILABLE') from None
                if error.reason=='PREMIUM_REQUIRED':raise APIError(403,'A conta Spotify conectada precisa ter Premium para reproduzir este trecho.','SPOTIFY_PREMIUM_REQUIRED') from None
                if error.reason=='INSUFFICIENT_SCOPE':raise APIError(403,'Faltou permitir a reprodução no Spotify. Desconecte e conecte sua conta para autorizar.','SPOTIFY_PERMISSION_REQUIRED') from None
                if error.reason in ('RESTRICTION_VIOLATED','TRACK_NOT_PLAYABLE'):raise APIError(403,'O Spotify não permite reproduzir esta faixa nessa conta. Tente outra música.','SPOTIFY_TRACK_UNAVAILABLE') from None
                if error.status==403:raise APIError(403,'O Spotify recusou o acesso. Confira se essa conta está autorizada no aplicativo Ressoa.','SPOTIFY_ACCESS_DENIED') from None
                if error.status==404:raise APIError(404,'Esta faixa não está disponível no Spotify.','SPOTIFY_TRACK_UNAVAILABLE') from None
                raise APIError(503,'O Spotify está indisponível no momento. Tente novamente em instantes.','SPOTIFY_UNAVAILABLE') from None

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
