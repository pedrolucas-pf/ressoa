"""Small read-only integrations. No account tokens, audio downloads, or lyric files."""
import json
import re
import random
import time
import unicodedata
from html import unescape
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

_CACHE = {}
_LOCK = Lock()

class ServiceError(Exception):
    pass

def _get(url, *, accept='application/json'):
    request = Request(url, headers={'User-Agent': 'Ressoa/0.6 (https://ressoa.onrender.com)', 'Accept': accept})
    try:
        with urlopen(request, timeout=12) as response:
            return response.read(4_000_000).decode('utf-8')
    except HTTPError as error:
        if error.code == 404:
            return None
        raise ServiceError('O serviço de música está temporariamente indisponível.') from error
    except (OSError, ValueError) as error:
        raise ServiceError('Não foi possível consultar o serviço de música.') from error

def _json(url):
    text = _get(url)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError as error:
        raise ServiceError('O serviço devolveu uma resposta inválida.') from error

def _cached(key, callback):
    now = time.monotonic()
    with _LOCK:
        item = _CACHE.get(key)
        if item and item[0] > now:
            return item[1]
    value = callback()
    with _LOCK:
        if len(_CACHE) >= 150:
            _CACHE.clear()
        _CACHE[key] = (now + 300, value)
    return value

def _https(value):
    if isinstance(value, str) and value.startswith('https://'):
        return value
    return ''

def deezer_track(item):
    album = item.get('album') or {}
    release = album.get('release_date') or item.get('release_date') or ''
    return {
        'catalogId': f"deezer:{int(item['id'])}", 'provider': 'deezer',
        'title': item.get('title', ''), 'artist': item.get('artist', {}).get('name', ''),
        'album': album.get('title', ''), 'year': str(release)[:4],
        'duration': item.get('duration', 0),
        'releaseDate': release, 'trackReleaseDate': item.get('release_date', ''),
        'contributors': [person.get('name', '') for person in item.get('contributors', []) if person.get('name')],
        'bpm': item.get('bpm', 0), 'isrc': item.get('isrc', ''),
        'explicit': item.get('explicit_lyrics') if isinstance(item.get('explicit_lyrics'), bool) else None,
        'artwork': _https(item.get('album', {}).get('cover_big') or item.get('album', {}).get('cover_medium')),
        'previewUrl': _https(item.get('preview')), 'url': f"https://www.deezer.com/track/{int(item['id'])}"
    }


def login_artwork():
    """Random distinct MPB/Brazilian rock covers from the verified local catalog."""
    def fetch():
        data = json.loads((Path(__file__).resolve().parent/'web'/'assets'/'login-artwork.json').read_text(encoding='utf-8'))
        covers = {}
        for item in data:
            artwork = _https(item.get('artwork'))
            if artwork:
                covers.setdefault(artwork, item)
        return list(covers.values())
    pool = _cached(('login-artwork-mpb-rock',), fetch)
    return {'covers': random.sample(pool, min(20, len(pool))), 'provider': 'deezer'}

def spotify_track(query):
    match = re.fullmatch(r'(?:https://open\.spotify\.com/(?:intl-[a-zA-Z-]+/)?track/|spotify:track:)([A-Za-z0-9]{22})(?:\?[^\s]*)?/?', query)
    if not match:
        raise ValueError('Use um link completo de faixa do Spotify.')
    track_id = match.group(1)
    def fetch():
        source = f'https://open.spotify.com/track/{track_id}'
        metadata = _json('https://open.spotify.com/oembed?' + urlencode({'url': source}))
        if not metadata:
            raise ValueError('Esta faixa do Spotify não foi encontrada.')
        # Public metadata included in the official, unauthenticated Embed page.
        html = _get(f'https://open.spotify.com/embed/track/{track_id}', accept='text/html')
        script = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html or '', re.S)
        if not script:
            raise ServiceError('Não foi possível conferir os dados desta faixa.')
        try:
            entity = json.loads(script.group(1))['props']['pageProps']['state']['data']['entity']
        except (KeyError, ValueError, TypeError) as error:
            raise ServiceError('Não foi possível conferir os dados desta faixa.') from error
        artists = ', '.join(artist['name'] for artist in entity.get('artists', []))
        if entity.get('type') != 'track' or not artists:
            raise ValueError('Use um link de música, não de playlist ou álbum.')
        return {'catalogId': f'spotify:{track_id}', 'provider': 'spotify', 'spotifyId': track_id,
                'title': entity.get('name') or metadata['title'], 'artist': artists, 'album': '',
                'year': entity.get('releaseDate', {}).get('isoString', '')[:4],
                'duration': round(entity.get('duration', 0) / 1000),
                'artwork': _https(metadata.get('thumbnail_url')), 'previewUrl': '', 'url': source}
    return _cached(('spotify', track_id), fetch)

def search_tracks(query,offset=0):
    query = query.strip()
    if type(offset) is not int or not 0<=offset<=240:raise ValueError('Página de busca inválida.')
    if len(query) < 2 or len(query) > 180:
        raise ValueError('Digite de 2 a 180 caracteres.')
    if query.startswith(('https://open.spotify.com/', 'spotify:')):
        return {'results': [spotify_track(query)] if not offset else [], 'provider': 'spotify','nextOffset':None}
    direct=re.fullmatch(r'(?:https://(?:www\.)?deezer\.com/(?:[a-z]{2}/)?track/|deezer:)([0-9]{1,16})(?:\?[^\s]*)?/?',query)
    if direct:return dict(results=[get_track('deezer:'+direct.group(1))] if not offset else [],provider='deezer',nextOffset=None)
    if query.startswith(('http://','https://')):raise ValueError('Use o link de uma faixa do Spotify ou Deezer.')
    def fetch():
        data = _json('https://api.deezer.com/search?' + urlencode({'q': query, 'limit': 20,'index':offset}))
        if not isinstance(data, dict) or 'error' in data:
            raise ServiceError('A busca de músicas está indisponível.')
        raw=list(data.get('data') or []);has_more=bool(data.get('next'))
        simplified=''.join(c for c in unicodedata.normalize('NFKD',query) if not unicodedata.combining(c))
        simplified=re.sub(r'\s*[-–—]\s*',' ',simplified)
        if len(raw)<4 and simplified!=query:
            try:
                extra=_json('https://api.deezer.com/search?'+urlencode(dict(q=simplified,limit=20,index=offset)))
                if isinstance(extra,dict) and not extra.get('error'):raw.extend(extra.get('data') or []);has_more=has_more or bool(extra.get('next'))
            except ServiceError:pass
        results={}
        for item in raw:
            if isinstance(item,dict) and item.get('id') and item.get('artist',{}).get('name'):
                result=deezer_track(item);results.setdefault(result['catalogId'],result)
        return {'results': list(results.values()), 'provider': 'deezer','nextOffset':offset+20 if has_more and offset<240 else None}
    return _cached(('search', query.casefold(),offset), fetch)

def get_track(catalog_id):
    match = re.fullmatch(r'deezer:([0-9]{1,16})', catalog_id)
    if not match:
        raise ValueError('Faixa inválida.')
    def fetch():
        data = _json(f'https://api.deezer.com/track/{match.group(1)}')
        if not data or 'error' in data:
            raise ValueError('Faixa não encontrada.')
        return deezer_track(data)
    return _cached(('track', catalog_id), fetch)

def _normalize(value):
    value = re.sub(r'\s+-\s+(?:remix(?:ed)?|remaster(?:ed)?|original album).*$', '', value, flags=re.I)
    return ''.join(char for char in unicodedata.normalize('NFKD', value).casefold() if char.isalnum())

def timed_lyrics(value, duration=0):
    if not isinstance(value,str):return []
    value=value[:180000]
    # Do not infer timing for LRC files with a separate, unsupported offset.
    if any(int(offset) for offset in re.findall(r'\[offset:([+-]?\d+)\]',value,re.I)):return []
    stamp=r'\[(\d{1,4}):([0-5]\d)(?:[.:](\d{1,3}))?\]'
    groups={}
    for line in value.splitlines()[:2000]:
        match=re.fullmatch('((?:'+stamp+r')+)(.*)',line.strip())
        if not match:continue
        content=match.group(5).strip()
        for minute,second,fraction in re.findall(stamp,match.group(1)):
            start=round(int(minute)*60+int(second)+(int(fraction)/10**len(fraction) if fraction else 0),3)
            if start>86400 or (duration and start>duration):continue
            groups.setdefault(start,[])
            if content not in groups[start]:groups[start].append(content)
        if len(groups)>=1200:break
    times=sorted(groups);lines=[]
    for index,start in enumerate(times):
        end=times[index+1] if index+1<len(times) else duration if duration>start else None
        for content in groups[start]:
            if content and (not duration or start<duration):lines.append(dict(start=start,end=end,text=content))
    return lines[:600]


def lyrics(title, artist, album='', duration=0):
    if not title or not artist or max(len(title), len(artist), len(album)) > 240:
        raise ValueError('Música e artista são necessários.')
    duration = max(0, min(float(duration or 0), 86400))
    def fetch():
        params = {'track_name': title, 'artist_name': artist}
        if album:
            params['album_name'] = album
        if duration:
            params['duration'] = round(duration)
        record = _json('https://lrclib.net/api/get?' + urlencode(params)) if duration and album else None
        if not record or 'error' in record:
            data = _json('https://lrclib.net/api/search?' + urlencode({'track_name': title, 'artist_name': artist}))
            matches = [item for item in data or [] if isinstance(item, dict)
                       and _normalize(item.get('trackName', '')) == _normalize(title)
                       and _normalize(item.get('artistName', '')) == _normalize(artist)
                       and (not duration or abs(float(item.get('duration', 0)) - duration) <= 4)] if isinstance(data, list) else []
            record = next((item for item in matches if _normalize(item.get('albumName', '')) == _normalize(album)), None) or (matches[0] if matches else None)
        if not record:
            return {'status': 'not_found'}
        if record.get('instrumental'):
            return {'status': 'instrumental', 'source': 'LRCLIB'}
        record_duration=record.get('duration')
        timeline=timed_lyrics(record.get('syncedLyrics'),record_duration if type(record_duration) in (int,float) and 0<record_duration<=86400 else duration)
        text = record.get('plainLyrics') or re.sub(r'\[\d+:\d+(?:[.:]\d+)?\]|\[(?:offset|ar|ti|al|by|length|re|ve):[^\]]*\]', '', record.get('syncedLyrics') or '',flags=re.I).strip()
        if not text:
            return {'status': 'not_found'}
        return {'status': 'found', 'text': text[:60000], 'lines':timeline,'source': 'LRCLIB',
                'sourceUrl': f"https://lrclib.net/api/get/{int(record['id'])}"}
    return _cached(('lyrics', title, artist, album, duration), fetch)
