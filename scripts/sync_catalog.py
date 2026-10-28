"""Refresh the small, explicit catalog using Spotify's public oEmbed endpoint."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TRACK_IDS = ['6jVWIRz01vnJ1VE8LtWK6Q', '3iof6EclqePezHDibBiykI', '7oz1o6N5NDdTXQCZSfB3SO', '0UtoASDXmEeZklHfKlqz8s', '1UsAjRCSavihMYsspqJz4e', '43BCxznTSBLcXzu4lJ8KW5']

def fetch(track_id):
    source = f'https://open.spotify.com/track/{track_id}'
    request = Request('https://open.spotify.com/oembed?' + urlencode({'url': source}), headers={'User-Agent': 'Ressoa/0.3 (local music journal)'})
    with urlopen(request, timeout=25) as response:
        data = json.load(response)
    return {'id': track_id, 'url': source, 'title': data['title'], 'artwork': data['thumbnail_url']}

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        catalog = list(pool.map(fetch, TRACK_IDS))
    output = {'retrievedAt': datetime.now(timezone.utc).isoformat(), 'tracks': catalog}
    (Path(__file__).resolve().parents[1]/'web'/'spotify-catalog.js').write_text('export const spotifyCatalog = ' + json.dumps(output, ensure_ascii=False, indent=2) + ';\n', encoding='utf-8')
    print(f'{len(catalog)} faixas e capas verificadas pelo oEmbed do Spotify.')
