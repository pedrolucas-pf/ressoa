export const tracks = [];
export const musicDetails = [];

function httpsAsset(value, type) {
  try {
    const url = new URL(value);
    const allowed = type === 'preview' ? ['dzcdn.net'] : ['dzcdn.net', 'spotifycdn.com', 'scdn.co'];
    return url.protocol === 'https:' && allowed.some(host => url.hostname === host || url.hostname.endsWith(`.${host}`)) ? url.href : '';
  } catch { return ''; }
}
export function sanitizeTrack(value) {
  if (!value || !['spotify', 'deezer'].includes(value.provider)) return null;
  const match = new RegExp(value.provider === 'spotify' ? '^spotify:([A-Za-z0-9]{22})$' : '^deezer:([0-9]+)$').exec(value.catalogId || '');
  if (!match || typeof value.title !== 'string' || !value.title.trim() || typeof value.artist !== 'string' || !value.artist.trim()) return null;
  return {
    catalogId: `${value.provider}:${match[1]}`, provider: value.provider, spotifyId: value.provider === 'spotify' ? match[1] : '',
    title: value.title.slice(0, 240), artist: value.artist.slice(0, 180), album: typeof value.album === 'string' ? value.album.slice(0, 180) : '',
    year: /^\d{4}$/.test(value.year || '') ? value.year : '', duration: Math.max(0, Math.min(Number(value.duration) || 0, 86400)),
    artwork: httpsAsset(value.artwork, 'artwork'), previewUrl: httpsAsset(value.previewUrl, 'preview'),
    releaseDate: /^\d{4}-\d{2}-\d{2}$/.test(value.releaseDate || '') ? value.releaseDate : '',
    trackReleaseDate: /^\d{4}-\d{2}-\d{2}$/.test(value.trackReleaseDate || '') ? value.trackReleaseDate : '',
    contributors: Array.isArray(value.contributors) ? value.contributors.filter(name=>typeof name==='string').slice(0,15).map(name=>name.slice(0,180)) : [],
    bpm: Math.max(0,Math.min(Number(value.bpm)||0,400)), isrc: /^[A-Za-z0-9]{12}$/.test(value.isrc||'') ? value.isrc : '',
    explicit: typeof value.explicit==='boolean' ? value.explicit : null,
    url: value.provider === 'spotify' ? `https://open.spotify.com/track/${match[1]}` : `https://www.deezer.com/track/${match[1]}`
  };
}
function append(track) {
  tracks.push({ title: track.title, artist: track.artist, album: track.album, year: track.year, duration: track.duration });
  musicDetails.push({ ...track, id: track.spotifyId || track.catalogId.split(':')[1], history: '', meaning: '', credits: '', sources: [] });
}
export function registerTrack(value) {
  const track = sanitizeTrack(value);
  if (!track) throw new Error('Não foi possível selecionar esta música.');
  const existing = musicDetails.findIndex(detail => detail.catalogId === track.catalogId);
  if (existing >= 0) {
    const detail = musicDetails[existing];
    for (const [key, value] of Object.entries(track)) {
      if (value !== '' && value !== null && (!Array.isArray(value) || value.length) && (typeof value !== 'number' || value > 0)) detail[key] = value;
    }
    Object.assign(tracks[existing], {title:detail.title,artist:detail.artist,album:detail.album,year:detail.year,duration:detail.duration});
    return existing;
  }
  append(track);
  return tracks.length - 1;
}
export function resetCatalog() {
  tracks.length = 0;
  musicDetails.length = 0;
}
